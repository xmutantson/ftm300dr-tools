"""Patch documented user-channel fields in a validated FTM-300DR template."""
from __future__ import annotations

import ftm300dr_format as fmt
from ftm300dr_reader import read_channel
from neutral import Duplex, ToneMode


def write_backup(template: bytes, channels, callsign: str | None = None) -> bytes:
    fmt.validate_backup(template)
    channels = list(channels)
    slots = [ch.index + 1 for ch in channels]
    if len(slots) != len(set(slots)):
        raise ValueError("Duplicate destination channel slots")
    for slot, ch in zip(slots, channels):
        fmt.validate_slot(slot)
        fmt.validate_channel(ch)
    data = bytearray(template)
    if callsign:
        cs = callsign.encode("ascii")
        if len(cs) > fmt.CALLSIGN_LEN or any(x < 32 or x > 126 for x in cs):
            raise ValueError("Callsign must be at most 10 printable ASCII characters")
        data[fmt.CALLSIGN_OFFSET:fmt.CALLSIGN_OFFSET + fmt.CALLSIGN_LEN] = cs.ljust(fmt.CALLSIGN_LEN, b"\xff")
    # Records 1000..1099 and their name/length entries have unknown roles.
    for slot in range(1, fmt.USER_CHANNEL_COUNT + 1):
        clear_channel(data, slot)
    for slot, ch in zip(slots, channels):
        write_channel(data, slot, ch)
    return bytes(data)


def write_channel(data: bytearray, slot: int, ch) -> None:
    """Patch changed field groups only; name-only edits preserve every record byte.

    Unsupported existing values may be retained. Changing a record with unknown
    semantics requires a supported channel model; no undocumented encoding is guessed.
    All validation completes before mutating the caller's buffer.
    """
    fmt.validate_backup(data)
    fmt.validate_slot(slot)
    old = read_channel(data, slot)
    mo, no, lo = fmt.mem_offset(slot), fmt.name_offset(slot), fmt.name_len_offset(slot)
    rec = bytearray(data[mo:mo + fmt.REC_SIZE])
    if old is None:
        rec = bytearray(fmt.encode_record(ch))
    else:
        metadata = {"index", "name", "bank", "source_slot"}
        if any(getattr(old, key) != getattr(ch, key) for key in old.__dataclass_fields__ if key not in metadata):
            encoded = fmt.encode_record(ch)

            def patch_fields(masks):
                for byte, mask in masks.items():
                    rec[byte] = (rec[byte] & (~mask & 0xFF)) | (encoded[byte] & mask)

            if ch.rx_freq_hz != old.rx_freq_hz:
                patch_fields({2: 0xFF, 3: 0xFF, 4: 0xFF})
                if fmt.band_params(ch.rx_freq_hz)[:2] != fmt.band_params(old.rx_freq_hz)[:2]:
                    patch_fields({0: 0x0F, 5: 0x0F})
            if ch.duplex != old.duplex:
                patch_fields({1: 0x07})
            if ch.duplex == Duplex.SPLIT and (ch.tx_freq_hz != old.tx_freq_hz or ch.duplex != old.duplex):
                patch_fields({6: 0xFF, 7: 0xFF, 8: 0xFF})
            if ch.duplex in (Duplex.PLUS, Duplex.MINUS) and (ch.offset_hz != old.offset_hz or ch.duplex != old.duplex):
                patch_fields({13: 0xFF})
            if ch.mode != old.mode:
                patch_fields({1: 0xF0})
            if ch.tone_mode != old.tone_mode:
                patch_fields({5: 0xF0})
            if ch.tone_mode in (ToneMode.TONE, ToneMode.TSQL) and (ch.ctcss_tx_hz != old.ctcss_tx_hz or ch.tone_mode != old.tone_mode):
                patch_fields({9: 0x3F})
            if ch.tone_mode == ToneMode.DTCS and (ch.dtcs_code != old.dtcs_code or ch.tone_mode != old.tone_mode):
                patch_fields({10: 0x7F})
            if ch.power != old.power:
                patch_fields({9: 0xC0})
            if ch.skip != old.skip:
                patch_fields({0: 0x60})
    name_changed = old is None or ch.name != old.name
    if name_changed:
        name = fmt.encode_name(ch.name)
        length = fmt.name_len_bytes(ch.name)
    data[mo:mo + fmt.REC_SIZE] = rec
    if name_changed:
        data[no:no + fmt.NAME_SIZE] = name
        data[lo:lo + fmt.NAME_LEN_SIZE] = length


def clear_channel(data: bytearray, slot: int) -> None:
    fmt.validate_backup(data)
    fmt.validate_slot(slot)
    mo, no, lo = fmt.mem_offset(slot), fmt.name_offset(slot), fmt.name_len_offset(slot)
    data[mo:mo + fmt.REC_SIZE] = fmt.EMPTY_RECORD
    data[no:no + fmt.NAME_SIZE] = bytes([fmt.NAME_PAD]) * fmt.NAME_SIZE
    data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.NAME_LEN_EMPTY
