"""Core conversion logic (no GUI): read FT-60 image + banks, lay channels out into
contiguous 300DR memory blocks by bank priority, apply field selection, and write the
backup. The GUI (ftm300dr_gui.py) is a thin wrapper over these functions.

Bank handling: the FTM-300DR has no user banks, so each included FT-60 bank's channels
are placed in a CONTIGUOUS block of 300DR channel numbers, in the user's priority order.
A channel in several banks lands in its highest-priority included bank (group primacy).
"""
from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_chirp"))

from ft60_reader import memory_to_neutral            # noqa: E402
from neutral import Duplex, ToneMode, Power, OpMode, Mode  # noqa: E402
from ftm300dr_writer import write_backup             # noqa: E402
from backup_io import read_backup_file, save_backup
from ftm300dr_format import validate_channel

MAX_CH = 999
UNBANKED = "(un-banked)"


def load_source(img_path: str):
    """-> (channels: {slot: NeutralChannel}, bank_members: {bank: set(slot)}, bank_order: [bank])."""
    from chirp.drivers import ft60
    radio = ft60.FT60Radio(img_path)
    lo, hi = radio.get_features().memory_bounds
    channels = {}
    for slot in range(lo, hi + 1):
        m = radio.get_memory(slot)
        if not m.empty:
            channels[slot] = memory_to_neutral(m, slot - 1)

    bank_members, bank_order = {}, []
    for model in radio.get_mapping_models():
        for mp in model.get_mappings():
            name = mp.get_name()
            members = {x.number for x in model.get_mapping_memories(mp) if x.number in channels}
            bank_members[name] = members
            bank_order.append(name)
    return with_unbanked(channels, bank_members, bank_order)


def with_unbanked(channels, bank_members, bank_order):
    """Add the same synthetic bank for all callers, once, without changing inputs."""
    members = {b: set(slots) for b, slots in bank_members.items()}
    order = list(bank_order)
    banked = set().union(*members.values()) if members else set()
    unbanked = set(channels) - banked
    if unbanked:
        if UNBANKED in members:
            raise ValueError(f"Source bank name {UNBANKED!r} is reserved")
        members[UNBANKED] = unbanked
        order.append(UNBANKED)
    return channels, members, order


def assign_slots(channels, bank_members, priority, included,
                 include_unbanked=True, gap=0, start=1):
    """Resolve each channel to one 300DR slot.

    priority: bank names ordered high->low. included: set of bank names to use.
    Returns list of dicts: {target, source, bank} ordered by target slot.
    """
    if not isinstance(start, int) or isinstance(start, bool) or not 1 <= start <= MAX_CH:
        raise ValueError("Start must be an integer in 1..999")
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
        raise ValueError("Gap must be a nonnegative integer")
    if len(priority) != len(set(priority)) or not set(priority) <= set(bank_members) or not set(included) <= set(priority):
        raise ValueError("Bank priority/inclusion contains duplicate or unknown banks")
    inc = [b for b in priority if b in included]
    owner = {}
    for slot in channels:
        owner[slot] = next((b for b in inc if slot in bank_members.get(b, ())), None)

    layout, cur = [], start
    for b in inc:
        members = sorted(s for s in channels if owner[s] == b)
        for s in members:
            layout.append({"target": cur, "source": s, "bank": b})
            cur += 1
        if members:
            cur += gap
    if include_unbanked:
        banked = set().union(*(slots for b, slots in bank_members.items() if b != UNBANKED)) if bank_members else set()
        for s in sorted(s for s in channels if owner[s] is None and s not in banked):
            layout.append({"target": cur, "source": s, "bank": UNBANKED})
            cur += 1
    return layout


def apply_fields(ch, *, copy_name=True, copy_tone=True, copy_shift=True,
                 copy_power=True, copy_skip=True, copy_narrow=True, op_mode=OpMode.FM,
                 copy_tuning_step=False):
    c = copy.copy(ch)
    if not copy_name:
        c.name = ""
    if not copy_tone:
        c.tone_mode = ToneMode.NONE
    if not copy_shift:
        if c.duplex == Duplex.OFF:
            raise ValueError("Receive-only channels cannot be converted to transmitting simplex channels")
        c.duplex = Duplex.NONE
        c.tx_freq_hz = c.rx_freq_hz
        c.offset_hz = 0
    if not copy_power:
        c.power = Power.HIGH
    if not copy_skip:
        c.skip = False
    if not copy_narrow and c.mode == Mode.NFM:
        c.mode = Mode.FM            # force wide
    if not copy_tuning_step:
        c.tuning_step_hz = 0        # explicitly unmapped; GUI/documents disclose omission
    c.op_mode = op_mode
    return c


@dataclass(frozen=True)
class ConversionPlan:
    channels: tuple
    report: tuple
    dropped: tuple


def build_plan(channels, bank_members, *, priority, included, fields,
               include_unbanked=True, gap=0, start=1):
    """One snapshot for preview, output and report. Overflow is visible, never saved."""
    layout = assign_slots(channels, bank_members, priority, included,
                          include_unbanked=include_unbanked, gap=gap, start=start)

    out_channels, report, dropped = [], [], []
    for item in layout:
        if item["target"] > MAX_CH:
            dropped.append(item)
            continue
        c = apply_fields(channels[item["source"]], **fields)
        c.index = item["target"] - 1
        out_channels.append(c)
        report.append({"target": item["target"], "source": item["source"],
                       "bank": item["bank"], "name": c.name, "freq_hz": c.rx_freq_hz})

    return ConversionPlan(tuple(out_channels), tuple(report), tuple(dropped))


def generate_plan(plan, template_path, output_path, *, callsign=None, source_path=None):
    if plan.dropped:
        raise ValueError(f"Layout exceeds channel 999 by {len(plan.dropped)} channels; reduce gaps or included banks")
    if not plan.channels:
        raise ValueError("No channels selected; refusing to erase the user-channel table")
    for ch, row in zip(plan.channels, plan.report):
        try:
            validate_channel(ch)
        except ValueError as exc:
            raise ValueError(f"Source channel {row['source']} -> target {row['target']}: {exc}") from exc
    template = read_backup_file(template_path)
    out = write_backup(template, plan.channels, callsign=callsign)
    protected = [template_path] + ([source_path] if source_path else [])
    save_backup(output_path, out, protected_paths=protected)
    return list(plan.report), []


def generate(img_path, template_path, output_path, *, priority, included, fields,
             callsign, include_unbanked=True, gap=0, start=1):
    channels, bank_members, _ = load_source(img_path)
    plan = build_plan(channels, bank_members, priority=priority, included=included,
                      fields=fields, include_unbanked=include_unbanked, gap=gap, start=start)
    return generate_plan(plan, template_path, output_path, callsign=callsign, source_path=img_path)
