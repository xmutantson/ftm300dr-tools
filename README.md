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

- **Python 3.8+** with **tkinter** (bundled with the standard python.org installer).
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

Everything in the file that the tools don't understand is carried over verbatim from your template,
so the radio accepts it. There is **no checksum** to forge.

## Caveats

- Reverse-engineered, **not** official. Not affiliated with or endorsed by Yaesu. Use at your own
  risk; keep a known-good backup before restoring anything.
- Validated against a current-firmware FTM-300DR; a future firmware could change the layout.
- **Tuning step** is the one channel field not yet mapped (the radio auto-steps, so this rarely
  matters for memory channels). **DCS** encoding is implemented from the FTM-400 map but untested.

## License

GPL-3.0 (the migrator links against CHIRP, which is GPL-3.0). See [LICENSE](LICENSE).
