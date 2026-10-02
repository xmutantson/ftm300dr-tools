# FTM-300DR tools

Two small, self-contained Python/Tkinter programs for the **Yaesu FTM-300DR / FTM-300DE**,
which [CHIRP does not support](https://chirpmyradio.com/issues/8129). They work entirely through
the radio's **microSD backup file** (`CLNFTM300D.dat`) — no programming cable required.

1. **`ftm300dr_gui.py` — FT-60 → FTM-300DR migrator.** Reads a Yaesu FT-60 CHIRP `.img`, lets you
   pick which FT-60 **banks** to include and in what priority, and writes the channels into an
   FTM-300DR backup. The 300DR has no user banks, so each bank becomes a **contiguous block of
   channel numbers** (a channel in several banks lands in its highest-priority bank). Carries
   frequency, name, CTCSS/TSQL tone, repeater shift + offset, split (satellite) TX, power,
   scan-skip, and FM-narrow.
2. **`ftm300dr_editor.py` — standalone FTM-300DR memory editor.** Open any `CLNFTM300D.dat`,
   view/add/edit/delete channels, and save. The CHIRP-equivalent this radio never got.

The binary format was reverse-engineered from controlled SD backups and cross-checked against the
sibling **FTM-400D** (CHIRP issue #1469 and [kz7zzz/ftm-400d](https://github.com/kz7zzz/ftm-400d)).
Full byte map: **[MEMORY_MAP.md](MEMORY_MAP.md)**.

## Requirements

- **Python 3.11** with **tkinter** (the offline suite is tested on Python 3.11).
- The **editor** needs nothing else.
- The **migrator** additionally needs CHIRP (to read FT-60 `.img` files):

  ```sh
  git clone --depth 1 https://github.com/kk7ds/chirp _chirp
  pip install pyserial pyyaml requests six
  ```

  (The real radio CHIRP is on GitHub as above — the PyPI package named `chirp` is an unrelated
  audio library.)

## Run

```sh
python ftm300dr_editor.py     # standalone editor
python ftm300dr_gui.py        # FT-60 -> FTM-300DR migrator
```

On Windows you can double-click `launch_editor.bat` / `launch_gui.bat`.

## How to use it with the radio

1. **You need a template.** Make a real backup of your radio first: insert a microSD card
   (**≤32 GB, FAT32, formatted in the radio**), then `SD CARD → 1 BACKUP → WRITE TO SD → ALL`.
   That writes `\FTM300D\BACKUP\CLNFTM300D.dat`. Keep a copy — it's your golden recovery file and
   the template these tools patch.
2. Run a tool, load the template (and, for the migrator, your FT-60 `.img`), and generate.
3. Copy the resulting file back to `\FTM300D\BACKUP\CLNFTM300D.dat` on the card, then on the radio
   `SD CARD → 1 BACKUP → READ FROM SD → ALL`.

The migrator replaces **user slots 1..999** in the template. The extra 100 record,
name, and name-length entries have unknown roles and are preserved, as are settings
outside the user tables (except an explicitly supplied callsign). This preservation
does not establish radio acceptance of a generated file.

The editor patches only changed fields. A name-only edit leaves the entire channel
record untouched, including unknown bytes, TSQL/DCS, custom offsets, and priority
skip. RX frequencies are displayed and parsed with six decimal MHz places, retaining
every integer Hz on the codec's 625 Hz grid. Offset entry is in MHz on a 50 kHz grid.
Inactive split-frequency and tone bytes are retained when editing other fields.

Both tools require the expected size and `AH071$` header. Saves use a sibling
temporary file, flush and verify its exact bytes, then atomically replace the output.
The migrator refuses to overwrite its source image or template. The editor protects
the file originally opened: use **Save As** to another path; subsequent saves can
replace that output. Failed saves retain the session's unsaved state. Opening another
file or closing the editor prompts to save, discard, or cancel when edits are pending.

The migrator uses the loaded source snapshot and one conversion plan for preview,
output, and report. Unbanked channels form a reorderable synthetic bank. Overlapping
bank membership is deduplicated by included-bank priority. Overflow past slot 999
and an empty selection block output; channels are never silently dropped. Browse to
load a changed source path before generating again.

## Caveats

- Reverse-engineered, **not** official. Not affiliated with or endorsed by Yaesu. Use at your own
  risk; keep a known-good backup before restoring anything.
- The historical format observations are documented in MEMORY_MAP.md. The changes in
  this revision have **not been tested on radio hardware**; future firmware may differ.
- Fresh encoding supports analog FM/NFM in the implemented 137–174 MHz and 400–480 MHz
  RX bands, simplex, plus/minus offsets, explicit split TX, none/TONE/TSQL/DCS tone
  modes, High/Mid/Low power, and none/S/P scan flags. These are codec capabilities,
  not a guarantee that every frequency or mode is usable on a radio.
- AM, receive-only (`off`), cross/reverse tone modes, separate RX/TX CTCSS values,
  non-NN DCS polarity, and AMS/DN/VW have no supported encoding and are rejected.
  AMS is not offered in the GUI. Unsupported values already in a backup can be
  retained in a name-only edit; other edits may be blocked pending a supported model.
- **Tuning step is explicitly omitted by migration**, as stated in the GUI. The
  low-level encoder rejects a requested nonzero tuning step. Existing editor records
  retain unknown step bits; changing bands uses the known band defaults.
- FT-60 CHIRP memories use one CTCSS value (`rtone`, `has_ctone=False`), so TSQL uses
  it for both TX and RX. Unrecognized CHIRP vocabulary is rejected. The FT-60 driver
  does not expose per-memory DCS polarity (`has_dtcs_polarity=False`); this converter
  does not transfer the radio's global polarity setting. DCS encoding derives from
  the FTM-400 map and remains hardware-unverified.
- Channel names must be at most 16 printable ASCII characters, callsigns at most 10.
  Unsupported tones, names, offsets, and off-grid frequencies are rejected rather
  than rounded or truncated. Disabling a copy option intentionally resets that field;
  disabling shift copying cannot turn a receive-only source into a transmitting channel.

## Offline verification

```sh
python -B -m unittest discover -s tests -v
```

The stdlib regression suite uses synthetic backups and temporary files only. It covers
record preservation, exact frequencies, unsupported field rejection, FT-60 mapping,
bank planning, overflow, save failures, and headless editor/GUI callbacks. CHIRP is
imported only when actually reading an image, so it is not needed for these tests.
These tests do not establish CHIRP `.img` integration or hardware compatibility.
Real-widget GUI validation was unavailable in the test environment because local
Tcl runtime/resource loading prevented Tk initialization.

## License

GPL-3.0 (the migrator links against CHIRP, which is GPL-3.0). See [LICENSE](LICENSE).
