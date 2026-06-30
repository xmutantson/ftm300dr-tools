# Yaesu FTM-300DR / FTM-300DE SD-backup memory map

Byte-level layout of the radio's microSD backup file `CLNFTM300D.dat` (written by
`SD CARD → 1 BACKUP → WRITE TO SD → ALL`, and the file ADMS-12 reads).

Reverse-engineered from controlled single-variable SD backups and validated on a real radio. The
per-record **bit layout** is independently corroborated by the sibling **Yaesu FTM-400D**, whose
format is the same Yaesu C4FM SD-backup family (FTM-400 file magic `AH034$` vs FTM-300 `AH071$`):
CHIRP issue [#1469](https://chirpmyradio.com/issues/1469) and
[github.com/kz7zzz/ftm-400d](https://github.com/kz7zzz/ftm-400d). Absolute offsets below are
FTM-300-specific.

## File

- Fixed size **0x18000 (98304) bytes**; the rest is `0xFF` padding.
- Header magic ASCII **`AH071$`** at offset 0.
- **No file checksum** — editing the channel/name tables and re-restoring is accepted as-is.

| range            | contents |
|------------------|----------|
| 0x0000–0x0080    | header (magic, counts) |
| 0x0080–0x00A0    | VFO A / VFO B |
| 0x00A0–0x0800    | settings (callsign ASCII @0x2C8, APRS, etc.) |
| 0x0800–0x4CB0    | **memory channel table** — 16 bytes/channel, channel *N* @ `0x800 + (N-1)*16` (999 ch) |
| 0x4CB0–0x5546    | **name-length table** — 2 bytes/channel |
| 0x10000–0x144B0  | **name table** — 16 bytes/channel, ASCII, `0xFF`-padded |
| (elsewhere)      | APRS / GPS / settings carried over verbatim |

## 16-byte channel record

Channel *N* (1-based) at `0x800 + (N-1)*16`.

| byte  | field |
|-------|-------|
| 0     | bit7 = **in-use**; bits 5–6 = **scan-skip** (0 none / 1 `S` / 2 `P`); low bits = band (0x01 VHF, 0x03 UHF) |
| 1     | hi-nibble = mode (`0x4` = FM); **bit5 (0x20) = NFM/narrow**; **bit2 (0x04) = odd-split**; bits 0–1 = duplex (0 simplex / 2 `−` / 3 `+`) |
| 2–4   | **RX frequency** (see below) |
| 5     | hi-nibble = **tone mode** (1 = TONE/encode, 2 = TSQL, 4 = DTCS); low nibble = band-step |
| 6–8   | **split TX frequency** (same BCD encoding) when odd-split is set |
| 9     | bits 6–7 = **TX power** (0 = High, 0x40 = Mid, 0x80 = Low); bits 0–5 = **CTCSS index** |
| 10    | **DCS code index** (1-based into the standard DCS list; 0 = none) |
| 11    | `0x0F` constant |
| 13    | **repeater offset ÷ 50 kHz** (e.g. 0x0C = 600 kHz, 0x64 = 5 MHz) |
| 12, 14, 15 | unknown (tuning step likely lives here — still unmapped) |

### Frequency (bytes 2–4)

```
freq_Hz = (bcd(b2 & 0x0F)*100 + bcd(b3)) * 1_000_000   # integer MHz (packed BCD)
        +  bcd(b4) * 10_000                            # 10 kHz steps (packed BCD)
        +  (b2 >> 4) * 625                             # sub-10 kHz fine field
bcd(x)  = (x >> 4) * 10 + (x & 0x0F)
```

The high nibble of byte 2 is a weighted fine-step field (bit3 = +5 kHz, bit2 = +2.5 kHz,
bit1 = +1.25 kHz), i.e. `nibble * 0.625 kHz`. Examples: `01 46 52` = 146.520 MHz; `44 62 56` =
462.5625 MHz (446... +2.5 kHz). Representable down to a 1.25 kHz grid.

### Tones

- **CTCSS** is an index into the standard 50-tone table (67.0 … 254.1 Hz); byte 9 bits 0–5.
- **DCS** is a 1-based index into the standard DCS code list (023 … 754); byte 10.
- The tone *mode* (off / TONE / TSQL / DTCS) is the high nibble of byte 5.

## Name table + name-length table

- **Name** of channel *N* @ `0x10000 + (N-1)*16`: up to 16 ASCII bytes, `0xFF`-padded.
- **Name length** of channel *N* @ `0x4CB0 + (N-1)*2`, big-endian: `(1 << (16 - len)) - 1`
  (6 chars → `0x03FF`, 9 → `0x007F`, **0 → `0xFFFF` = blank**). The radio reads *this* as the tag
  length — without it set, the name bytes are ignored and the channel shows blank.

## Notes

- The alpha tag is shown only for the channel on the **operating (white) band**; toggle with `[A/B]`.
- The 300DR has **no user banks/zones** — only automatic band grouping (M-ALL / M-VHF / M-UHF…)
  and one user group (M-GRP).
- FM bandwidth (wide/narrow) is also exposed globally in the setup menu, but the per-channel narrow
  bit (byte 1 bit 5) is stored independently.
