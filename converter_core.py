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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_chirp"))

from chirp.drivers import ft60                       # noqa: E402
from ft60_reader import memory_to_neutral            # noqa: E402
from neutral import Duplex, ToneMode, Power, OpMode, Mode  # noqa: E402
from ftm300dr_writer import write_backup             # noqa: E402

MAX_CH = 999


def load_source(img_path: str):
    """-> (channels: {slot: NeutralChannel}, bank_members: {bank: set(slot)}, bank_order: [bank])."""
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
    return channels, bank_members, bank_order


def assign_slots(channels, bank_members, priority, included,
                 include_unbanked=True, gap=0, start=1):
    """Resolve each channel to one 300DR slot.

    priority: bank names ordered high->low. included: set of bank names to use.
    Returns list of dicts: {target, source, bank} ordered by target slot.
    """
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
        for s in sorted(s for s in channels if owner[s] is None):
            layout.append({"target": cur, "source": s, "bank": "(unbanked)"})
            cur += 1
    return layout


def apply_fields(ch, *, copy_name=True, copy_tone=True, copy_shift=True,
                 copy_power=True, copy_skip=True, copy_narrow=True, op_mode=OpMode.FM):
    c = copy.copy(ch)
    if not copy_name:
        c.name = ""
    if not copy_tone:
        c.tone_mode = ToneMode.NONE
    if not copy_shift:
        c.duplex = Duplex.NONE
    if not copy_power:
        c.power = Power.HIGH
    if not copy_skip:
        c.skip = False
    if not copy_narrow:
        c.mode = Mode.FM            # force wide
    c.op_mode = op_mode
    return c


def generate(img_path, template_path, output_path, *, priority, included, fields,
             callsign, include_unbanked=True, gap=0, start=1):
    """Build the output .dat. Returns (report_rows, dropped) where report_rows are
    dicts {target, source, bank, name, freq_hz} and dropped lists overflow channels."""
    channels, bank_members, _ = load_source(img_path)
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

    template = open(template_path, "rb").read()
    out = write_backup(template, out_channels, callsign=callsign)
    with open(output_path, "wb") as fh:
        fh.write(out)
    return report, dropped
