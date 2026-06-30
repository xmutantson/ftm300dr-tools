"""Standalone FTM-300DR memory editor — what CHIRP can't do for this radio.

Open a CLNFTM300D.dat backup, view/add/edit/delete memory channels, and save. All
edits go straight into the reverse-engineered binary; everything else in the file is
carried through untouched, so the radio accepts it on READ FROM SD.

Run:  launch_editor.bat   (or  .venv\\Scripts\\python.exe ftm300dr_editor.py)
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import ftm300dr_format as fmt
from ftm300dr_reader import read_backup, read_channel
from ftm300dr_writer import write_channel, clear_channel
from neutral import NeutralChannel, Duplex, ToneMode, Power, Mode, OpMode

DEF_DIR = os.path.dirname(os.path.abspath(__file__))
SHIFTS = {"none": Duplex.NONE, "−": Duplex.MINUS, "+": Duplex.PLUS, "split": Duplex.SPLIT}
SHIFT_LABEL = {Duplex.NONE: "none", Duplex.MINUS: "−", Duplex.PLUS: "+",
               Duplex.SPLIT: "split", Duplex.OFF: "none"}
TONES = [f"{t:.1f}" for t in fmt.CTCSS]


class ChannelDialog(tk.Toplevel):
    def __init__(self, master, title, slot=None, ch=None, slot_editable=True, used=()):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.used = set(used)
        f = ttk.Frame(self, padding=10)
        f.grid()
        r = 0
        ttk.Label(f, text="Channel #").grid(row=r, column=0, sticky="w")
        self.v_slot = tk.IntVar(value=slot or 1)
        sp = ttk.Spinbox(f, from_=1, to=999, width=8, textvariable=self.v_slot)
        sp.grid(row=r, column=1, sticky="w")
        if not slot_editable:
            sp.configure(state="disabled")
        r += 1
        ttk.Label(f, text="Name (≤16)").grid(row=r, column=0, sticky="w")
        self.v_name = tk.StringVar(value=ch.name if ch else "")
        ttk.Entry(f, textvariable=self.v_name, width=20).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="RX freq (MHz)").grid(row=r, column=0, sticky="w")
        self.v_freq = tk.StringVar(value=f"{ch.rx_freq_hz/1e6:.4f}" if ch else "146.5200")
        ttk.Entry(f, textvariable=self.v_freq, width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="TX freq (split only)").grid(row=r, column=0, sticky="w")
        _tx = ch.tx_freq_hz if (ch and ch.duplex == Duplex.SPLIT) else (ch.rx_freq_hz if ch else 146_520_000)
        self.v_tx = tk.StringVar(value=f"{_tx/1e6:.4f}")
        ttk.Entry(f, textvariable=self.v_tx, width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Repeater shift").grid(row=r, column=0, sticky="w")
        self.v_shift = tk.StringVar(value=SHIFT_LABEL.get(ch.duplex, "none") if ch else "none")
        ttk.Combobox(f, textvariable=self.v_shift, values=list(SHIFTS), width=7,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        self.v_tone = tk.BooleanVar(value=bool(ch and ch.tone_mode in (ToneMode.TONE, ToneMode.TSQL)))
        ttk.Checkbutton(f, text="CTCSS tone", variable=self.v_tone).grid(row=r, column=0, sticky="w")
        self.v_ctcss = tk.StringVar(value=f"{(ch.ctcss_tx_hz if ch else 100.0):.1f}")
        ttk.Combobox(f, textvariable=self.v_ctcss, values=TONES, width=8,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="TX power").grid(row=r, column=0, sticky="w")
        self.v_pwr = tk.StringVar(value=(ch.power.value if ch else "High"))
        ttk.Combobox(f, textvariable=self.v_pwr, values=["High", "Mid", "Low"], width=6,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        self.v_skip = tk.BooleanVar(value=bool(ch and ch.skip))
        ttk.Checkbutton(f, text="Scan-skip (S)", variable=self.v_skip).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.v_narrow = tk.BooleanVar(value=bool(ch and getattr(ch.mode, "value", "") == "NFM"))
        ttk.Checkbutton(f, text="NFM (narrow)", variable=self.v_narrow).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        bf = ttk.Frame(f)
        bf.grid(row=r, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(bf, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok())
        self.grab_set()
        self.wait_window()

    def _ok(self):
        try:
            slot = int(self.v_slot.get())
            if not (1 <= slot <= 999):
                raise ValueError("Channel # must be 1–999")
            hz = round(float(self.v_freq.get()) * 1_000_000)
            fmt.freq_encode_bytes(hz)        # validate it's representable
            dup = SHIFTS.get(self.v_shift.get(), Duplex.NONE)
            tx = round(float(self.v_tx.get()) * 1_000_000) if dup == Duplex.SPLIT else hz
            if dup == Duplex.SPLIT:
                fmt.freq_encode_bytes(tx)
        except Exception as e:
            messagebox.showerror("Invalid", str(e), parent=self)
            return
        ch = NeutralChannel(
            index=slot - 1, name=self.v_name.get().strip()[:16], rx_freq_hz=hz, tx_freq_hz=tx,
            duplex=dup, mode=Mode.NFM if self.v_narrow.get() else Mode.FM,
            tone_mode=ToneMode.TONE if self.v_tone.get() else ToneMode.NONE,
            ctcss_tx_hz=float(self.v_ctcss.get()), power=Power(self.v_pwr.get()),
            skip=self.v_skip.get(), op_mode=OpMode.FM, source_slot=slot)
        self.result = (slot, ch)
        self.destroy()


class Editor(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.data = None
        self.path = None
        self.dirty = False

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Button(top, text="Open .dat…", command=self.open).pack(side="left")
        ttk.Button(top, text="Save As…", command=self.save_as).pack(side="left", padx=4)
        self.lbl = ttk.Label(top, text="no file loaded")
        self.lbl.pack(side="left", padx=10)

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(bar, text="Add channel", command=self.add).pack(side="left")
        ttk.Button(bar, text="Edit", command=self.edit).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", command=self.delete).pack(side="left")

        cols = ("name", "freq", "shift", "tone", "power", "skip")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Ch")
        self.tree.column("#0", width=50, anchor="center")
        for c, (h, w) in {"name": ("Name", 130), "freq": ("RX MHz", 85), "shift": ("Shift", 45),
                          "tone": ("CTCSS", 60), "power": ("Power", 55), "skip": ("Skip", 40)}.items():
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=2, column=0, sticky="nsew")
        vs.grid(row=2, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self.edit())

    # ---------- file ----------
    def open(self):
        p = filedialog.askopenfilename(filetypes=[("Backup", "*.dat"), ("All", "*.*")])
        if p:
            self._load(p)

    def _load(self, path):
        try:
            data = open(path, "rb").read()
            if len(data) != fmt.FILE_SIZE or data[:6] != fmt.MAGIC:
                if not messagebox.askyesno("Unexpected file",
                                           "This doesn't look like an FTM-300DR backup. Open anyway?"):
                    return
            self.data = bytearray(data)
            self.path = path
            self.dirty = False
            self._refresh()
        except Exception as e:
            messagebox.showerror("Open error", str(e))

    def save_as(self):
        if self.data is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".dat", filetypes=[("Backup", "*.dat")],
                                         initialfile="CLNFTM300D.dat")
        if p:
            open(p, "wb").write(bytes(self.data))
            self.dirty = False
            self.path = p
            self._refresh()
            messagebox.showinfo("Saved", f"Wrote {p}")

    # ---------- table ----------
    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.data is None:
            return
        chans = read_backup(self.data)
        for slot in sorted(chans):
            c = chans[slot]
            tone = f"{c.ctcss_tx_hz:.1f}" if c.tone_mode in (ToneMode.TONE, ToneMode.TSQL) else ""
            self.tree.insert("", "end", iid=str(slot), text=str(slot),
                             values=(c.name, f"{c.rx_freq_hz/1e6:.4f}",
                                     SHIFT_LABEL.get(c.duplex, ""), tone, c.power.value,
                                     "S" if c.skip else ""))
        flag = " *unsaved*" if self.dirty else ""
        self.lbl.config(text=f"{os.path.basename(self.path or '')} — {len(chans)} channels{flag}")

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def add(self):
        if self.data is None:
            messagebox.showinfo("Add", "Open a .dat first.")
            return
        used = set(read_backup(self.data))
        nxt = next((i for i in range(1, 1000) if i not in used), 1)
        dlg = ChannelDialog(self, "Add channel", slot=nxt, used=used)
        if dlg.result:
            slot, ch = dlg.result
            write_channel(self.data, slot, ch)
            self.dirty = True
            self._refresh()
            if self.tree.exists(str(slot)):
                self.tree.selection_set(str(slot)); self.tree.see(str(slot))

    def edit(self):
        slot = self._sel()
        if slot is None:
            return
        ch = read_channel(self.data, slot)
        dlg = ChannelDialog(self, f"Edit channel {slot}", slot=slot, ch=ch, slot_editable=False)
        if dlg.result:
            _, newch = dlg.result
            write_channel(self.data, slot, newch)
            self.dirty = True
            self._refresh()
            self.tree.selection_set(str(slot))

    def delete(self):
        slot = self._sel()
        if slot is None:
            return
        if messagebox.askyesno("Delete", f"Clear channel {slot}?"):
            clear_channel(self.data, slot)
            self.dirty = True
            self._refresh()


def main():
    root = tk.Tk()
    root.title("FTM-300DR memory editor")
    root.geometry("560x620")
    Editor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
