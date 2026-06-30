"""Write an FTM-300DR backup by patching a known-good template:
  - set the callsign,
  - clear the whole memory + name tables to the radio's empty defaults,
  - write our channels (neutral.NeutralChannel.index 0-based -> radio channel 1-based).
Everything we don't understand (header, settings blocks, markers, padding) is carried
over byte-for-byte from the template, so the radio sees a file shaped exactly like one
it wrote itself.
"""
from __future__ import annotations

import ftm300dr_format as fmt


def write_backup(template: bytes, channels, callsign: str | None = None) -> bytes:
    if len(template) != fmt.FILE_SIZE:
        raise ValueError(f"template is {len(template)} bytes, expected {fmt.FILE_SIZE}")
    data = bytearray(template)

    if callsign:
        cs = callsign.encode("ascii", "replace")[:fmt.CALLSIGN_LEN]
        field = cs + bytes([0xFF]) * (fmt.CALLSIGN_LEN - len(cs))
        data[fmt.CALLSIGN_OFFSET:fmt.CALLSIGN_OFFSET + fmt.CALLSIGN_LEN] = field

    # blank the memory records, name table, and name-length table
    blank_name = bytes([fmt.NAME_PAD]) * fmt.NAME_SIZE
    for i in range(fmt.REC_COUNT):
        mo = fmt.MEM_TABLE_BASE + i * fmt.REC_SIZE
        data[mo:mo + fmt.REC_SIZE] = fmt.EMPTY_RECORD
        no = fmt.NAME_TABLE_BASE + i * fmt.NAME_SIZE
        data[no:no + fmt.NAME_SIZE] = blank_name
        lo = fmt.NAME_LEN_BASE + i * fmt.NAME_LEN_SIZE
        data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.NAME_LEN_EMPTY

    # write our channels
    for ch in channels:
        slot = ch.index + 1
        if not (1 <= slot <= 999):
            raise ValueError(f"channel slot {slot} out of range 1..999")
        mo = fmt.mem_offset(slot)
        data[mo:mo + fmt.REC_SIZE] = fmt.encode_record(ch)
        if ch.name:
            no = fmt.name_offset(slot)
            data[no:no + fmt.NAME_SIZE] = fmt.encode_name(ch.name)
            lo = fmt.name_len_offset(slot)
            data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.name_len_bytes(ch.name)

    return bytes(data)


def write_channel(data: bytearray, slot: int, ch) -> None:
    """Patch one channel (record + name + name-length) into a mutable backup."""
    mo = fmt.mem_offset(slot)
    data[mo:mo + fmt.REC_SIZE] = fmt.encode_record(ch)
    no = fmt.name_offset(slot)
    lo = fmt.name_len_offset(slot)
    if ch.name:
        data[no:no + fmt.NAME_SIZE] = fmt.encode_name(ch.name)
        data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.name_len_bytes(ch.name)
    else:
        data[no:no + fmt.NAME_SIZE] = bytes([fmt.NAME_PAD]) * fmt.NAME_SIZE
        data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.NAME_LEN_EMPTY


def clear_channel(data: bytearray, slot: int) -> None:
    """Reset one channel to the radio's empty default."""
    mo = fmt.mem_offset(slot)
    data[mo:mo + fmt.REC_SIZE] = fmt.EMPTY_RECORD
    no = fmt.name_offset(slot)
    data[no:no + fmt.NAME_SIZE] = bytes([fmt.NAME_PAD]) * fmt.NAME_SIZE
    lo = fmt.name_len_offset(slot)
    data[lo:lo + fmt.NAME_LEN_SIZE] = fmt.NAME_LEN_EMPTY
