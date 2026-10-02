"""FTM-300DR SD-backup (CLNFTM300D.dat) channel codecs.

Reverse-engineered from controlled SD backups and cross-checked against the FTM-400D
family (CHIRP issue #1469 / github.com/kz7zzz/ftm-400d). See MEMORY_MAP.md for the full
spec. 16-byte channel record (table @0x800, channel N @ 0x800 + (N-1)*16):

  byte0  bit7 in-use; bits5-6 scan-skip (1=S); low bits band (0x01 VHF / 0x03 UHF)
  byte1  hi-nibble mode (0x4 FM); bit5 NFM/narrow; bit2 odd-split; bits0-1 duplex (0 / 2 - / 3 +)
  byte2  low nibble MHz hundreds; HIGH nibble sub-10 kHz fine (5/2.5/1.25 kHz weighted bits)
  byte3  MHz tens+units packed BCD;  byte4 fractional packed BCD x 10 kHz
  byte5  hi-nibble tone mode (1 TONE / 2 TSQL / 4 DTCS); low nibble band-step
  bytes6-8  split TX freq (packed BCD) when odd-split
  byte9  bits6-7 power (00 Hi / 0x40 Mid / 0x80 Lo); bits0-5 CTCSS index
  byte10 DCS code index (1-based);  byte11 0x0f const;  byte13 repeater offset / 50 kHz
Name table @0x10000 (16 bytes/ch, ASCII, 0xFF pad); name-LENGTH table @0x4cb0 (2 bytes/ch).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

FILE_SIZE = 0x18000
MAGIC = b"AH071$"

MEM_TABLE_BASE = 0x800
REC_SIZE = 16
REC_COUNT = 1099
USER_CHANNEL_COUNT = 999  # remaining 100 records have unknown roles
NAME_TABLE_BASE = 0x10000
NAME_SIZE = 16
NAME_PAD = 0xFF
CALLSIGN_OFFSET = 0x2C8
CALLSIGN_LEN = 10

IN_USE_BIT = 0x80
# radio's default for an unprogrammed channel (144.000): 01 40 01 44 00 00 00 00 00 0c 00 0f 00 0c 00 00
EMPTY_RECORD = bytes([0x01, 0x40, 0x01, 0x44, 0, 0, 0, 0, 0, 0x0C, 0, 0x0F, 0, 0x0C, 0, 0])
assert len(EMPTY_RECORD) == 16

# Standard Yaesu/CHIRP 50-tone CTCSS table; the record stores the list index.
CTCSS = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4,
    100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5,
    141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5,
    210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
]
CTCSS_DEFAULT_IDX = CTCSS.index(100.0)   # 12

MODE_FM = 0x4
SHIFT_CODE = {"none": 0, "+": 3, "-": 2}
POWER_BITS = {"High": 0x00, "Mid": 0x40, "Low": 0x80}
POWER_BITS_INV = {v: k for k, v in POWER_BITS.items()}

# tone MODE = byte5 high nibble (FTM-400 "sql" field): 0 none / 1 TONE(encode) /
# 2 TSQL(tone squelch) / 4 DTCS. CTCSS index lives in byte9, DCS code index in byte10.
SQL_MODE = {"none": 0, "TONE": 1, "TSQL": 2, "DTCS": 4}
SQL_MODE_INV = {0: "none", 1: "TONE", 2: "TSQL", 4: "DTCS"}
SKIP_BIT = 5                              # scan-skip = byte0 bits 5-6 (SKIPS ['', 'S', 'P'])
ODDSPLIT_BIT = 0x04                       # byte1 bit2 = odd split; TX freq in bytes 6-8
NARROW_BIT = 0x20                         # byte1 bit5 = NFM (narrow): FM wide = 0x40, narrow = 0x60

# Standard DTCS code list; the record stores the 1-based index (0 = none).
DTCS_CODES = [
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74, 114, 115,
    116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252, 255, 261, 263, 265,
    266, 271, 274, 306, 311, 315, 325, 331, 332, 343, 346, 351, 356, 364, 365,
    371, 411, 412, 413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464, 465,
    466, 503, 506, 516, 523, 526, 532, 546, 565, 606, 612, 624, 627, 631, 632,
    654, 662, 664, 703, 712, 723, 731, 732, 734, 743, 754,
]


def dtcs_index(code: int) -> int:
    try:
        return DTCS_CODES.index(int(code)) + 1
    except (ValueError, TypeError):
        return 0


def bcd(x: int) -> int:
    return (x >> 4) * 10 + (x & 0x0F)


def to_bcd(x: int) -> int:
    return ((x // 10) << 4) | (x % 10)


def ctcss_index(hz: float) -> int:
    best = min(range(len(CTCSS)), key=lambda i: abs(CTCSS[i] - hz))
    return best


# --- band: (byte0 nibble, byte5 nibble, byte13) keyed off frequency ---
def band_params(freq_hz: int):
    f = freq_hz
    if 137_000_000 <= f < 174_000_000:        # "144 MHz band" (incl 2m + weather)
        return 0x01, 0x00, 0x0C
    if 400_000_000 <= f < 480_000_000:        # "430 MHz band" (incl 70cm + FRS/GMRS)
        return 0x03, 0x07, 0x64
    if 108_000_000 <= f < 137_000_000:        # AIR (unverified codes -> reuse VHF-ish)
        return 0x01, 0x00, 0x0C
    # fallback (unverified): treat by half-band
    return (0x03, 0x07, 0x64) if f >= 300_000_000 else (0x01, 0x00, 0x0C)


# --- frequency ---
def freq_decode(b2: int, b3: int, b4: int) -> int:
    mhz = (b2 & 0x0F) * 100 + bcd(b3)
    fine_khz = (b2 >> 4) * 625          # Hz, 0.625 kHz steps
    return mhz * 1_000_000 + bcd(b4) * 10_000 + fine_khz


def freq_encode_bytes(hz: int) -> tuple[int, int, int]:
    if not isinstance(hz, int) or not 0 < hz < 1_000_000_000:
        raise ValueError("Frequency must be an integer Hz value between 0 and 1000 MHz")
    mhz, frac = divmod(hz, 1_000_000)
    khz10, sub = divmod(frac, 10_000)
    fine, rem = divmod(sub, 625)
    if rem:
        raise ValueError(f"{hz} Hz not representable (residue {rem} Hz below 625 Hz grid)")
    if mhz >= 1000:
        raise ValueError(f"{hz} Hz: MHz>=1000 not supported")
    b2 = (fine << 4) | (mhz // 100)
    b3 = to_bcd(mhz % 100)
    b4 = to_bcd(khz10)
    return b2, b3, b4


# --- whole 16-byte record ---
def validate_backup(data) -> None:
    if len(data) != FILE_SIZE or bytes(data[:len(MAGIC)]) != MAGIC:
        raise ValueError(f"Expected an FTM-300DR backup: {FILE_SIZE} bytes with AH071$ header")


def validate_slot(slot: int) -> None:
    if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= USER_CHANNEL_COUNT:
        raise ValueError("Channel slot must be an integer in 1..999")


def mhz_text(hz: int) -> str:
    return f"{hz // 1_000_000}.{hz % 1_000_000:06d}"


def parse_mhz(text: str) -> int:
    try:
        hz = Decimal(text.strip()) * 1_000_000
        if not hz.is_finite() or hz != hz.to_integral_value():
            raise ValueError("Frequency must be a whole number of Hz")
        result = int(hz)
    except InvalidOperation as exc:
        raise ValueError("Invalid frequency") from exc
    freq_encode_bytes(result)
    return result


def skip_code(value) -> int:
    if value is False or value == "":
        return 0
    if value is True or value == "S":
        return 1
    if value == "P":
        return 2
    raise ValueError(f"Unsupported scan-skip value: {value!r}")


def validate_channel(ch) -> None:
    from neutral import Duplex, Mode, OpMode, ToneMode
    if ch.mode not in (Mode.FM, Mode.NFM):
        raise ValueError(f"Unsupported modulation: {ch.mode}")
    if ch.op_mode != OpMode.FM:
        raise ValueError("Only analog FM operating mode has an implemented encoding")
    if ch.duplex not in (Duplex.NONE, Duplex.PLUS, Duplex.MINUS, Duplex.SPLIT):
        raise ValueError(f"Unsupported duplex: {ch.duplex}; receive-only encoding is unknown")
    if ch.tone_mode not in (ToneMode.NONE, ToneMode.TONE, ToneMode.TSQL, ToneMode.DTCS):
        raise ValueError(f"Unsupported tone mode: {ch.tone_mode}")
    if ch.tuning_step_hz:
        raise ValueError("Tuning-step encoding is unknown")
    freq_encode_bytes(ch.rx_freq_hz)
    if not (137_000_000 <= ch.rx_freq_hz < 174_000_000 or 400_000_000 <= ch.rx_freq_hz < 480_000_000):
        raise ValueError("Band encoding is only implemented for 137-174 and 400-480 MHz")
    if ch.duplex == Duplex.SPLIT:
        freq_encode_bytes(ch.tx_freq_hz)
    elif ch.duplex in (Duplex.PLUS, Duplex.MINUS):
        if not isinstance(ch.offset_hz, int) or not 0 <= ch.offset_hz <= 255 * 50_000 or ch.offset_hz % 50_000:
            raise ValueError("Repeater offset must be 0..12.75 MHz on the 50 kHz grid")
        expected = ch.rx_freq_hz + (ch.offset_hz if ch.duplex == Duplex.PLUS else -ch.offset_hz)
        if ch.tx_freq_hz != expected:
            raise ValueError("TX frequency disagrees with repeater offset")
        freq_encode_bytes(expected)
    elif ch.tx_freq_hz != ch.rx_freq_hz:
        raise ValueError("Simplex TX frequency must equal RX frequency")
    if ch.tone_mode in (ToneMode.TONE, ToneMode.TSQL) and ch.ctcss_tx_hz not in CTCSS:
        raise ValueError("CTCSS tone is not in the supported table")
    if ch.tone_mode == ToneMode.TSQL and ch.ctcss_rx_hz != ch.ctcss_tx_hz:
        raise ValueError("Separate RX/TX CTCSS tones are unsupported")
    if ch.tone_mode == ToneMode.DTCS and (ch.dtcs_code not in DTCS_CODES or ch.dtcs_polarity != "NN"):
        raise ValueError("DCS requires a supported code and NN polarity")
    if ch.power not in POWER_BITS:
        raise ValueError(f"Unsupported power: {ch.power}")
    skip_code(ch.skip)
    encode_name(ch.name)


def encode_record(ch) -> bytes:
    """ch is a neutral.NeutralChannel (analog). Returns 16 bytes.
    Within-record layout corroborated by the FTM-400D RE (CHIRP #1469 / kz7zzz/ftm-400d).
    NOTE: scan-skip, DCS, and TSQL come from the FTM-400 sibling map (high confidence,
    same family) — verified on the 300 for skip via capture if available; DCS untested."""
    from neutral import Duplex
    validate_channel(ch)
    b0n, b5n, b13_def = band_params(ch.rx_freq_hz)
    tmode = ch.tone_mode.value if hasattr(ch.tone_mode, "value") else ch.tone_mode
    rec = bytearray(16)
    skip = skip_code(ch.skip)
    rec[0] = IN_USE_BIT | (skip << SKIP_BIT) | b0n
    rec[2], rec[3], rec[4] = freq_encode_bytes(ch.rx_freq_hz)
    narrow = NARROW_BIT if (getattr(ch.mode, "value", ch.mode) == "NFM") else 0
    if ch.duplex == Duplex.SPLIT:
        rec[1] = (MODE_FM << 4) | narrow | ODDSPLIT_BIT    # byte1 bit2 = odd-split
        rec[6], rec[7], rec[8] = freq_encode_bytes(ch.tx_freq_hz)   # split TX freq
    else:
        shift = {Duplex.NONE: "none", Duplex.PLUS: "+",
                 Duplex.MINUS: "-"}[ch.duplex]
        rec[1] = (MODE_FM << 4) | narrow | SHIFT_CODE[shift]
    rec[5] = (SQL_MODE.get(tmode, 0) << 4) | b5n
    idx = ctcss_index(ch.ctcss_tx_hz) if tmode in ("TONE", "TSQL") else CTCSS_DEFAULT_IDX
    pwr = POWER_BITS.get(ch.power.value if hasattr(ch.power, "value") else ch.power, 0x00)
    rec[9] = pwr | (idx & 0x3F)
    if tmode == "DTCS":
        rec[10] = dtcs_index(ch.dtcs_code) & 0x7F
    rec[11] = 0x0F
    if ch.duplex in (Duplex.MINUS, Duplex.PLUS):
        rec[13] = ch.offset_hz // 50_000
    else:
        rec[13] = b13_def
    return bytes(rec)


def decode_record(rec: bytes) -> dict:
    idx = rec[9] & 0x3F
    return {
        "in_use": bool(rec[0] & IN_USE_BIT),
        "skip": (rec[0] >> SKIP_BIT) & 0x3,                 # 0 none / 1 S / 2 P
        "freq_hz": freq_decode(rec[2], rec[3], rec[4]),
        "shift": "split" if (rec[1] & ODDSPLIT_BIT) else {0: "none", 2: "-", 3: "+"}.get(rec[1] & 0x03, "?"),
        "split_tx_hz": freq_decode(rec[6], rec[7], rec[8]) if (rec[1] & ODDSPLIT_BIT) else None,
        "mode": "NFM" if (rec[1] & NARROW_BIT) else "FM",
        "tone_mode": SQL_MODE_INV.get(rec[5] >> 4, "?"),
        "tone_on": (rec[5] >> 4) != 0,
        "ctcss_hz": CTCSS[idx] if idx < len(CTCSS) else None,
        "dcs_code": DTCS_CODES[rec[10] - 1] if 0 < rec[10] <= len(DTCS_CODES) else None,
        "power": POWER_BITS_INV.get(rec[9] & 0xC0, "?"),
        "offset_hz": rec[13] * 50_000,
    }


def encode_name(name: str) -> bytes:
    try:
        b = (name or "").encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Channel names must contain ASCII characters only") from exc
    if len(b) > NAME_SIZE or any(x < 32 or x > 126 for x in b):
        raise ValueError("Channel names must contain at most 16 printable ASCII characters")
    return b + bytes([NAME_PAD]) * (NAME_SIZE - len(b))


def decode_name(raw: bytes) -> str:
    return raw.split(b"\xff")[0].decode("ascii", "replace").rstrip()


def mem_offset(ch_1based: int) -> int:
    return MEM_TABLE_BASE + (ch_1based - 1) * REC_SIZE


def name_offset(ch_1based: int) -> int:
    return NAME_TABLE_BASE + (ch_1based - 1) * NAME_SIZE


# Name-LENGTH table: 2 bytes/channel right after the record table. The radio reads
# this as the tag length; 0xFFFF = length 0 = blank (so the name bytes are ignored).
NAME_LEN_BASE = 0x4CB0
NAME_LEN_SIZE = 2
NAME_LEN_EMPTY = b"\xff\xff"


def name_len_offset(ch_1based: int) -> int:
    return NAME_LEN_BASE + (ch_1based - 1) * NAME_LEN_SIZE


def name_len_bytes(name: str) -> bytes:
    """(1 << (16 - len)) - 1, big-endian. 6 chars->03 ff, 9->00 7f, 0->ff ff, 16->00 00."""
    n = len((name or "").encode("ascii", "replace")[:NAME_SIZE])
    v = (1 << (NAME_SIZE - n)) - 1
    return bytes([(v >> 8) & 0xFF, v & 0xFF])
