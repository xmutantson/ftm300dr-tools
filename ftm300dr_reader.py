"""Decode an FTM-300DR backup (CLNFTM300D.dat) back into NeutralChannels.
Used by the standalone editor and for round-trip validation.
"""
from __future__ import annotations

import ftm300dr_format as fmt
from neutral import NeutralChannel, Duplex, ToneMode, Power, Mode, OpMode

_DUP = {0: Duplex.NONE, 2: Duplex.MINUS, 3: Duplex.PLUS}
_PWR = {0x00: Power.HIGH, 0x40: Power.MID, 0x80: Power.LOW}
_TMODE = {0: ToneMode.NONE, 1: ToneMode.TONE, 2: ToneMode.TSQL, 4: ToneMode.DTCS}


def read_channel(data, slot: int):
    """Return a NeutralChannel for `slot` (1-based), or None if the slot is empty."""
    fmt.validate_backup(data)
    fmt.validate_slot(slot)
    rec = data[fmt.mem_offset(slot):fmt.mem_offset(slot) + fmt.REC_SIZE]
    if not (rec[0] & fmt.IN_USE_BIT):
        return None
    lenb = bytes(data[fmt.name_len_offset(slot):fmt.name_len_offset(slot) + 2])
    name = "" if lenb == fmt.NAME_LEN_EMPTY else fmt.decode_name(
        data[fmt.name_offset(slot):fmt.name_offset(slot) + fmt.NAME_SIZE])
    freq = fmt.freq_decode(rec[2], rec[3], rec[4])
    idx = rec[9] & 0x3F
    dcs = fmt.DTCS_CODES[rec[10] - 1] if 0 < rec[10] <= len(fmt.DTCS_CODES) else 23
    oddsplit = bool(rec[1] & fmt.ODDSPLIT_BIT)
    duplex = Duplex.SPLIT if oddsplit else _DUP.get(rec[1] & 0x03, Duplex.UNKNOWN)
    offset = rec[13] * 50_000
    tx = freq + offset if duplex == Duplex.PLUS else freq - offset if duplex == Duplex.MINUS else freq
    return NeutralChannel(
        index=slot - 1,
        name=name,
        rx_freq_hz=freq,
        tx_freq_hz=fmt.freq_decode(rec[6], rec[7], rec[8]) if oddsplit else tx,
        duplex=duplex,
        offset_hz=offset,
        mode=(Mode.NFM if rec[1] & fmt.NARROW_BIT else Mode.FM) if rec[1] & 0xD0 == 0x40 else Mode.UNKNOWN,
        tone_mode=_TMODE.get(rec[5] >> 4, ToneMode.UNKNOWN),
        ctcss_tx_hz=fmt.CTCSS[idx] if idx < len(fmt.CTCSS) else 0.0,
        ctcss_rx_hz=fmt.CTCSS[idx] if idx < len(fmt.CTCSS) else 0.0,
        dtcs_code=dcs if 0 < rec[10] <= len(fmt.DTCS_CODES) else 0,
        power=_PWR.get(rec[9] & 0xC0, Power.UNKNOWN),
        skip={0: "", 1: "S", 2: "P"}.get((rec[0] >> fmt.SKIP_BIT) & 3, "unknown"),
        op_mode=OpMode.FM,
        source_slot=slot,
    )


def read_backup(data) -> dict:
    """-> {slot: NeutralChannel} for every programmed channel (1..999)."""
    out = {}
    for slot in range(1, 1000):
        ch = read_channel(data, slot)
        if ch is not None:
            out[slot] = ch
    return out
