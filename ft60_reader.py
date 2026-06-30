"""Read a Yaesu FT-60 CHIRP .img clone into list[NeutralChannel].

Uses the real radio CHIRP (cloned under ./_chirp) purely as a library — only
the ft60 driver and core modules are imported, so the GUI/serial deps aren't
needed. The PyPI package named "chirp" is an unrelated audio library; do not
use it.
"""
from __future__ import annotations

import logging
import os
import sys

# --- make the cloned radio CHIRP importable (driver + core only) ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_CHIRP_SRC = os.path.join(_HERE, "_chirp")
if _CHIRP_SRC not in sys.path:
    sys.path.insert(0, _CHIRP_SRC)

logging.getLogger("chirp").setLevel(logging.ERROR)

from chirp.drivers import ft60  # noqa: E402  (registers the FT60 driver)

from neutral import (  # noqa: E402
    NeutralChannel, Duplex, Mode, ToneMode, OpMode, Power,
)

# --- mappings from CHIRP's chirp_common.Memory vocabulary to the neutral model ---
_DUPLEX = {"": Duplex.NONE, "+": Duplex.PLUS, "-": Duplex.MINUS,
           "split": Duplex.SPLIT, "off": Duplex.OFF}
_MODE = {"FM": Mode.FM, "NFM": Mode.NFM, "AM": Mode.AM}
_TMODE = {"": ToneMode.NONE, "Tone": ToneMode.TONE, "TSQL": ToneMode.TSQL,
          "DTCS": ToneMode.DTCS, "Cross": ToneMode.CROSS}


def _map_power(power) -> Power:
    s = str(power or "").lower()
    if "low" in s:
        return Power.LOW
    if "mid" in s or "med" in s:
        return Power.MID
    return Power.HIGH  # FT-60 high / unknown -> High


def _tx_freq(rx: int, duplex: str, offset: int) -> int:
    if duplex == "+":
        return rx + offset
    if duplex == "-":
        return rx - offset
    if duplex == "split":
        return offset           # CHIRP stores the explicit TX freq in offset
    if duplex == "off":
        return 0                # receive only
    return rx                   # simplex


def memory_to_neutral(m, index: int, default_op_mode: OpMode = OpMode.FM) -> NeutralChannel:
    return NeutralChannel(
        index=index,
        name=(m.name or "").strip(),
        rx_freq_hz=int(m.freq),
        tx_freq_hz=_tx_freq(int(m.freq), m.duplex, int(m.offset)),
        duplex=_DUPLEX.get(m.duplex, Duplex.NONE),
        offset_hz=int(m.offset),
        tuning_step_hz=int(round(float(m.tuning_step) * 1000)),
        mode=_MODE.get(m.mode, Mode.FM),
        tone_mode=_TMODE.get(m.tmode, ToneMode.NONE),
        ctcss_tx_hz=float(m.rtone),
        ctcss_rx_hz=float(m.ctone),
        dtcs_code=int(m.dtcs),
        dtcs_polarity=m.dtcs_polarity or "NN",
        power=_map_power(m.power),
        skip=bool(m.skip),                       # "" -> False, "S"/"P" -> True
        op_mode=default_op_mode,
        bank=None,
        cross_mode=getattr(m, "cross_mode", "") if m.tmode == "Cross" else "",
        source_slot=m.number,
    )


def read_ft60(path: str, default_op_mode: OpMode = OpMode.FM) -> list[NeutralChannel]:
    """Parse an FT-60 .img clone into neutral channels (populated slots only)."""
    radio = ft60.FT60Radio(path)
    lo, hi = radio.get_features().memory_bounds
    out: list[NeutralChannel] = []
    idx = 0
    for slot in range(lo, hi + 1):
        m = radio.get_memory(slot)
        if m.empty:
            continue
        out.append(memory_to_neutral(m, idx, default_op_mode))
        idx += 1
    return out
