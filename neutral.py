"""Neutral channel model — the contract between any reader and any writer.

A reader (e.g. ft60_reader) parses a source radio into list[NeutralChannel].
A writer (e.g. ftm300dr_writer) serializes NeutralChannel[] into the target
backup. Field mappings live in the reader/writer, never inline between them.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, fields
from enum import Enum
from typing import Optional


class Duplex(str, Enum):
    UNKNOWN = "unknown"  # preserve existing records; never synthesize this value
    NONE = "none"     # simplex, tx == rx
    PLUS = "+"        # tx = rx + offset
    MINUS = "-"       # tx = rx - offset
    SPLIT = "split"   # tx is an independent frequency
    OFF = "off"       # receive only, no tx


class Mode(str, Enum):
    UNKNOWN = "unknown"
    FM = "FM"
    NFM = "NFM"
    AM = "AM"


class ToneMode(str, Enum):
    UNKNOWN = "unknown"
    NONE = "none"
    TONE = "TONE"     # CTCSS encode only (TX tone)        -> 300DR "TN"
    TSQL = "TSQL"     # CTCSS encode + decode               -> 300DR "TSQ"
    DTCS = "DTCS"     # digital coded squelch               -> 300DR "DCS"
    CROSS = "cross"   # asymmetric tx/rx signalling (see cross_mode)


class OpMode(str, Enum):
    """Only FM encoding is currently supported; other values must be rejected."""
    FM = "FM"
    AMS = "AMS"
    DN = "DN"
    VW = "VW"


class Power(str, Enum):
    UNKNOWN = "unknown"
    HIGH = "High"
    MID = "Mid"
    LOW = "Low"


@dataclass
class NeutralChannel:
    index: int                       # 0-based position in the output list
    name: str = ""
    rx_freq_hz: int = 0
    tx_freq_hz: int = 0
    duplex: Duplex = Duplex.NONE
    offset_hz: int = 0
    tuning_step_hz: int = 0
    mode: Mode = Mode.FM
    tone_mode: ToneMode = ToneMode.NONE
    ctcss_tx_hz: float = 88.5
    ctcss_rx_hz: float = 88.5
    dtcs_code: int = 23
    dtcs_polarity: str = "NN"
    power: Power = Power.HIGH
    skip: bool | str = False         # False/True legacy aliases; "", "S", "P"
    op_mode: OpMode = OpMode.FM      # 300DR-specific; defaulted for analog FT-60 source
    bank: Optional[int] = None
    cross_mode: str = ""             # populated only when tone_mode == CROSS
    source_slot: Optional[int] = None  # original slot number on the source radio

    def to_row(self) -> dict:
        d = asdict(self)
        # enums -> their string values for flat CSV/JSON
        for k, v in d.items():
            if isinstance(v, Enum):
                d[k] = v.value
        return d


CSV_FIELDS = [f.name for f in fields(NeutralChannel)]


def write_csv(channels: list[NeutralChannel], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for ch in channels:
            w.writerow(ch.to_row())
