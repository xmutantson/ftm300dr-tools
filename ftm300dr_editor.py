"""Standalone FTM-300DR memory editor — what CHIRP can't do for this radio.

Open a CLNFTM300D.dat backup, view/add/edit/delete memory channels, and save. All
edits go straight into the reverse-engineered binary; everything else in the file is
carried through untouched. Hardware acceptance requires separate validation.

Run:  launch_editor.bat   (or  .venv\\Scripts\\python.exe ftm300dr_editor.py)
"""
from __future__ import annotations

import os
from dataclasses import replace
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import ftm300dr_format as fmt
from ftm300dr_reader import read_backup, read_channel
from ftm300dr_writer import write_channel, clear_channel
from neutral import NeutralChannel, Duplex, ToneMode, Power, Mode, OpMode
from backup_io import read_backup_file, save_backup

DEF_DIR = os.path.dirname(os.path.abspath(__file__))
SHIFTS = {d.value: d for d in (Duplex.NONE, Duplex.MINUS, Duplex.PLUS, Duplex.SPLIT)}
SHIFT_LABEL = {d: d.value for d in Duplex}
TONES = [f"{t:.1f}" for t in fmt.CTCSS]


class ChannelDialog(tk.Toplevel):
    def __init__(self, master, title, slot=None, ch=None, slot_editable=True, used=()):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.used = set(used)
        self.original = ch
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
        self.v_freq = tk.StringVar(value=fmt.mhz_text(ch.rx_freq_hz) if ch else "146.520000")
        ttk.Entry(f, textvariable=self.v_freq, width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="TX freq (split only)").grid(row=r, column=0, sticky="w")
        _tx = ch.tx_freq_hz if (ch and ch.duplex == Duplex.SPLIT) else (ch.rx_freq_hz if ch else 146_520_000)
        self.v_tx = tk.StringVar(value=fmt.mhz_text(_tx))
        ttk.Entry(f, textvariable=self.v_tx, width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Repeater shift").grid(row=r, column=0, sticky="w")
        self.v_shift = tk.StringVar(value=SHIFT_LABEL.get(ch.duplex, "none") if ch else "none")
        ttk.Combobox(f, textvariable=self.v_shift, values=list(SHIFTS), width=7,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Offset (MHz)").grid(row=r, column=0, sticky="w")
        self.v_offset = tk.StringVar(value=fmt.mhz_text(ch.offset_hz if ch else 600_000))
        ttk.Entry(f, textvariable=self.v_offset, width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Tone mode").grid(row=r, column=0, sticky="w")
        self.v_tone = tk.StringVar(value=ch.tone_mode.value if ch else "none")
        ttk.Combobox(f, textvariable=self.v_tone, values=["none", "TONE", "TSQL", "DTCS"],
                     width=8, state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="CTCSS (Hz)").grid(row=r, column=0, sticky="w")
        self.v_ctcss = tk.StringVar(value=f"{(ch.ctcss_tx_hz if ch else 100.0):.1f}")
        ttk.Combobox(f, textvariable=self.v_ctcss, values=TONES, width=8,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="DCS code (NN)").grid(row=r, column=0, sticky="w")
        self.v_dcs = tk.StringVar(value=str(ch.dtcs_code if ch else 23))
        ttk.Combobox(f, textvariable=self.v_dcs, values=[str(x) for x in fmt.DTCS_CODES],
                     width=8, state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="TX power").grid(row=r, column=0, sticky="w")
        self.v_pwr = tk.StringVar(value=(ch.power.value if ch else "High"))
        ttk.Combobox(f, textvariable=self.v_pwr, values=["High", "Mid", "Low"], width=6,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        self.v_skip = tk.StringVar(value=ch.skip if ch else "")
        ttk.Label(f, text="Scan skip").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_skip, values=["", "S", "P"], width=8,
                     state="readonly").grid(row=r, column=1, sticky="w")
        r += 1
        self.v_mode = tk.StringVar(value=ch.mode.value if ch else "FM")
        ttk.Label(f, text="Modulation").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_mode, values=["FM", "NFM"], width=8,
                     state="readonly").grid(row=r, column=1, sticky="w")
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
            if slot in self.used:
                raise ValueError(f"Channel {slot} is already occupied; use Edit instead")
            hz = fmt.parse_mhz(self.v_freq.get())
            dup = Duplex(self.v_shift.get())
            # Zero is a valid offset; parse without the positive-frequency restriction.
            from decimal import Decimal
            offset_value = Decimal(self.v_offset.get()) * 1_000_000
            if not offset_value.is_finite() or offset_value != offset_value.to_integral_value():
                raise ValueError("Offset must be a whole number of Hz")
            offset = int(offset_value)
            tx = fmt.parse_mhz(self.v_tx.get()) if dup == Duplex.SPLIT else hz
            if dup in (Duplex.PLUS, Duplex.MINUS):
                tx += offset if dup == Duplex.PLUS else -offset
            base = self.original or NeutralChannel(index=slot - 1)
            ctcss = float(self.v_ctcss.get())
            ch = replace(base, index=slot - 1, name=self.v_name.get(), rx_freq_hz=hz,
                         tx_freq_hz=tx, duplex=dup, offset_hz=offset, mode=Mode(self.v_mode.get()),
                         tone_mode=ToneMode(self.v_tone.get()), ctcss_tx_hz=ctcss,
                         ctcss_rx_hz=base.ctcss_rx_hz if ctcss == base.ctcss_tx_hz else ctcss,
                         dtcs_code=int(self.v_dcs.get()), power=Power(self.v_pwr.get()),
                         skip=self.v_skip.get(), source_slot=slot)
            # Validate against the existing raw record without mutating the session.
            write_channel(bytearray(self.master.data), slot, ch)
        except Exception as e:
            messagebox.showerror("Invalid", str(e), parent=self)
            return
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
        self.source_path = None
        master.protocol("WM_DELETE_WINDOW", self.close)

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
        if not self._may_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("Backup", "*.dat"), ("All", "*.*")])
        if p:
            self._load(p)

    def _load(self, path):
        try:
            data = read_backup_file(path)
            read_backup(data)   # finish parsing before replacing session state
            self.data = bytearray(data)
            self.path = path
            self.source_path = path
            self.dirty = False
            self._refresh()
        except Exception as e:
            messagebox.showerror("Open error", str(e))

    def save_as(self):
        if self.data is None:
            return False
        p = filedialog.asksaveasfilename(defaultextension=".dat", filetypes=[("Backup", "*.dat")],
                                         initialfile="CLNFTM300D.dat")
        if p:
            try:
                save_backup(p, bytes(self.data), protected_paths=[self.source_path] if self.source_path else [])
            except Exception as e:
                messagebox.showerror("Save error", str(e))
                return False
            self.dirty = False
            self.path = p
            self._refresh()
            messagebox.showinfo("Saved", f"Wrote {p}")
            return True
        return False

    def _may_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save changes before continuing?")
        if answer is None:
            return False
        return self.save_as() if answer else True

    def close(self):
        if self._may_discard():
            self.master.destroy()

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
                             values=(c.name, fmt.mhz_text(c.rx_freq_hz),
                                     SHIFT_LABEL.get(c.duplex, ""), tone, c.power.value,
                                     c.skip))
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
        nxt = next((i for i in range(1, 1000) if i not in used), None)
        if nxt is None:
            messagebox.showinfo("Add", "All 999 user channels are occupied.")
            return
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
