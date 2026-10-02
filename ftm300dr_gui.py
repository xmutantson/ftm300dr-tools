"""Self-contained Tkinter GUI: FT-60 .img  ->  FTM-300DR SD backup (CLNFTM300D.dat).

Pick the source image + a template backup, inspect each FT-60 bank's channels (expand a
bank), label and prioritize the banks (right-click for options), choose which settings to
copy, and generate. Banks become contiguous 300DR channel-number blocks (the 300DR has no
real banks); a channel in several banks lands in its highest-priority included bank.

Run:  launch_gui.bat   (or  .venv\\Scripts\\python.exe ftm300dr_gui.py)
"""
from __future__ import annotations

import csv
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog

import converter_core as cc
import ftm300dr_format as fmt
from backup_io import same_path
from neutral import OpMode, Duplex, ToneMode

DEF_IMG = ""        # browse to your FT-60 .img clone (CHIRP image)
DEF_TMPL = ""       # browse to a real FTM-300DR backup (CLNFTM300D.dat) to use as the template
DEF_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CLNFTM300D.dat")
UNBANKED = cc.UNBANKED


def _dup(ch):
    return {Duplex.PLUS: "+", Duplex.MINUS: "−", Duplex.SPLIT: "splt", Duplex.OFF: "off"}.get(ch.duplex, "")


def _tone(ch):
    return f"{ch.ctcss_tx_hz:.1f}" if ch.tone_mode in (ToneMode.TONE, ToneMode.TSQL) else ""


def _detail(ch):
    return f"{fmt.mhz_text(ch.rx_freq_hz)}  {_dup(ch):4} {ch.mode.value:3} {_tone(ch)}"


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(3, weight=1)

        self.channels: dict = {}
        self.bank_members: dict = {}
        self.bank_order: list = []
        self.labels: dict = {}
        self.included: set = set()
        self.last_report = []
        self.loaded_source_path = None

        self._build_files()
        self._build_main()
        self._build_actions()
        self._build_report()
        self.var_gap.trace_add("write", lambda *_: self._refresh_tree())

        if DEF_IMG and os.path.exists(DEF_IMG):
            self.var_img.set(DEF_IMG)
            self._load_image()

    # ---------- files ----------
    def _build_files(self):
        f = ttk.LabelFrame(self, text="Files", padding=6)
        f.grid(row=0, column=0, sticky="ew", pady=4)
        f.columnconfigure(1, weight=1)
        self.var_img = tk.StringVar()
        self.var_tmpl = tk.StringVar(value=DEF_TMPL if os.path.exists(DEF_TMPL) else "")
        self.var_out = tk.StringVar(value=DEF_OUT)
        self.var_call = tk.StringVar(value="")   # your callsign (leave blank to keep the template's)
        for i, (label, var, cmd) in enumerate([
            ("FT-60 image (.img)", self.var_img, self._pick_img),
            ("Template backup (.dat)", self.var_tmpl, self._pick_tmpl),
            ("Output file (.dat)", self.var_out, self._pick_out),
        ]):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", padx=2, pady=1)
            ttk.Entry(f, textvariable=var).grid(row=i, column=1, sticky="ew", padx=2)
            ttk.Button(f, text="Browse…", command=cmd).grid(row=i, column=2, padx=2)
        ttk.Label(f, text="Callsign").grid(row=3, column=0, sticky="w", padx=2)
        ttk.Entry(f, textvariable=self.var_call, width=12).grid(row=3, column=1, sticky="w", padx=2)

    def _pick_img(self):
        p = filedialog.askopenfilename(filetypes=[("FT-60 image", "*.img"), ("All", "*.*")])
        if p:
            self.var_img.set(p)
            self._load_image()

    def _pick_tmpl(self):
        p = filedialog.askopenfilename(filetypes=[("Backup", "*.dat"), ("All", "*.*")])
        if p:
            self.var_tmpl.set(p)

    def _pick_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".dat", filetypes=[("Backup", "*.dat")],
                                         initialfile="CLNFTM300D.dat")
        if p:
            self.var_out.set(p)

    # ---------- bank tree + options ----------
    def _build_main(self):
        wrap = ttk.Frame(self)
        wrap.grid(row=1, column=0, sticky="nsew", pady=4)
        wrap.columnconfigure(0, weight=3)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)

        bf = ttk.LabelFrame(wrap, text="Banks (top = highest priority) — expand to inspect, right-click for options",
                            padding=6)
        bf.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        bf.columnconfigure(0, weight=1)
        bf.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(bf, columns=("detail", "note"), show="tree headings",
                                 height=16, selectmode="browse")
        self.tree.heading("#0", text="Bank / channel")
        self.tree.heading("detail", text="freq  shift mode tone")
        self.tree.heading("note", text="→ lands at")
        self.tree.column("#0", width=240)
        self.tree.column("detail", width=200)
        self.tree.column("note", width=120)
        vs = ttk.Scrollbar(bf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("off", foreground="#999")
        self.tree.tag_configure("elsewhere", foreground="#999")
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-3>", self._popup)

        self.menu = tk.Menu(self.tree, tearoff=0)
        self.menu.add_command(label="Use / don't use", command=self._toggle_include)
        self.menu.add_command(label="Rename label…", command=self._rename)
        self.menu.add_separator()
        self.menu.add_command(label="Move up", command=lambda: self._move(-1))
        self.menu.add_command(label="Move down", command=lambda: self._move(1))

        btns = ttk.Frame(bf)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        for txt, cmd in [("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1)),
                         ("Use all", lambda: self._set_all(True)), ("Use none", lambda: self._set_all(False)),
                         ("Expand all", lambda: self._expand(True)), ("Collapse all", lambda: self._expand(False))]:
            ttk.Button(btns, text=txt, command=cmd).pack(side="left", padx=2)

        of = ttk.LabelFrame(wrap, text="Settings to copy / options", padding=6)
        of.grid(row=0, column=1, sticky="nsew")
        self.var_name = tk.BooleanVar(value=True)
        self.var_tone = tk.BooleanVar(value=True)
        self.var_shift = tk.BooleanVar(value=True)
        self.var_power = tk.BooleanVar(value=True)
        self.var_skip = tk.BooleanVar(value=True)
        self.var_narrow = tk.BooleanVar(value=True)
        for i, (txt, var) in enumerate([("Channel name (TAG)", self.var_name), ("Tone / squelch (CTCSS/DCS)", self.var_tone),
                                        ("Duplex / repeater offset", self.var_shift), ("TX power", self.var_power),
                                        ("Scan-skip flag", self.var_skip), ("FM narrow (NFM) flag", self.var_narrow)]):
            ttk.Checkbutton(of, text=txt, variable=var, command=self._refresh_tree).grid(row=i, column=0, columnspan=2, sticky="w")
        ttk.Label(of, text="Gap between blocks").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.var_gap = tk.IntVar(value=0)
        ttk.Spinbox(of, from_=0, to=50, width=5, textvariable=self.var_gap,
                    command=self._refresh_tree).grid(row=6, column=1, sticky="w")
        ttk.Label(of, text="Operating mode").grid(row=7, column=0, sticky="w")
        self.var_op = tk.StringVar(value="FM")
        ttk.Combobox(of, textvariable=self.var_op, values=["FM"], width=6,
                     state="readonly").grid(row=7, column=1, sticky="w")
        ttk.Label(of, text="(Un-banked channels appear as their\nown bank — use/reorder like any other.)",
                  foreground="#666").grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(of, text="Tuning step is not copied (unmapped).\nFM/NFM stored per channel; DCS unverified.",
                  foreground="#666").grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))

    # ---------- data / tree ----------
    def _load_image(self):
        try:
            channels, bank_members, order = cc.load_source(self.var_img.get())
        except Exception as e:
            self.var_img.set(self.loaded_source_path or "")
            messagebox.showerror("Load error", f"Could not read image:\n{e}")
            return
        self.channels, self.bank_members = channels, bank_members
        self.loaded_source_path = self.var_img.get()
        self.last_report = []
        self.report.delete("1.0", "end")
        self.bank_order = [b for b in order if self.bank_members.get(b)]
        self.labels = {b: b for b in self.bank_order}
        self.included = set(self.bank_order)
        self._refresh_tree()

    def _plan(self):
        return cc.build_plan(self.channels, self.bank_members, priority=self.bank_order,
                             included=set(self.included), fields=self._fields(),
                             include_unbanked=False, gap=self.var_gap.get(), start=1)

    def _refresh_tree(self):
        open_state = {b: self.tree.item(b, "open") for b in self.bank_order if self.tree.exists(b)}
        sel = self.tree.selection()
        try:
            plan = self._plan()
        except (ValueError, tk.TclError) as e:
            self.status.config(text=str(e))
            return
        self.tree.delete(*self.tree.get_children())
        layout = list(plan.report) + list(plan.dropped)
        planned_channels = {row["source"]: ch for row, ch in zip(plan.report, plan.channels)}
        self.status.config(text=f"Overflow: {len(plan.dropped)} channels; output blocked" if plan.dropped else f"Preview: {len(plan.channels)} channels")
        target_of = {it["source"]: it["target"] for it in layout}
        owner_of = {it["source"]: it["bank"] for it in layout}

        def label(b):
            return self.labels.get(b, b)

        for b in self.bank_order:
            members = sorted(self.bank_members.get(b, ()))
            here = [s for s in members if owner_of.get(s) == b]
            rng = ""
            if here:
                tg = sorted(target_of[s] for s in here)
                rng = f"ch {tg[0]}–{tg[-1]}"
            mark = "✔" if b in self.included else "·"
            tags = () if b in self.included else ("off",)
            self.tree.insert("", "end", iid=b, open=open_state.get(b, False), tags=tags,
                             text=f"{mark} {label(b)}",
                             values=(f"{b} · {len(here)}/{len(members)} here", rng))
            for s in members:
                ch = planned_channels.get(s, self.channels[s])
                if owner_of.get(s) == b:
                    note, ctag = f"ch {target_of[s]}", ()
                elif b in self.included:
                    note, ctag = f"→ {label(owner_of[s])}", ("elsewhere",)
                else:
                    note, ctag = "(bank off)", ("elsewhere",)
                self.tree.insert(b, "end", iid=f"{b}:{s}", tags=ctag,
                                 text=f"   {s:>3}  {ch.name}", values=(_detail(ch), note))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _selected_bank(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if ":" in iid:
            iid = self.tree.parent(iid)
        return iid if iid in self.bank_order else None

    def _popup(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.tree.selection_set(row)
            self.menu.tk_popup(e.x_root, e.y_root)

    def _on_double(self, _e):
        sel = self.tree.selection()
        if sel and sel[0] in self.bank_order:
            self._toggle_include()

    def _move(self, delta):
        b = self._selected_bank()
        if not b:
            return
        i = self.bank_order.index(b)
        j = i + delta
        if 0 <= j < len(self.bank_order):
            self.bank_order[i], self.bank_order[j] = self.bank_order[j], self.bank_order[i]
            self._refresh_tree()
            self.tree.selection_set(b)
            self.tree.see(b)

    def _toggle_include(self):
        b = self._selected_bank()
        if b:
            self.included.symmetric_difference_update({b})
            self._refresh_tree()
            self.tree.selection_set(b)

    def _set_all(self, on):
        self.included = set(self.bank_order) if on else set()
        self._refresh_tree()

    def _rename(self):
        b = self._selected_bank()
        if not b:
            return
        new = simpledialog.askstring("Bank label", f"Label for {b}:", initialvalue=self.labels.get(b, b))
        if new:
            self.labels[b] = new.strip()
            self._refresh_tree()
            self.tree.selection_set(b)

    def _expand(self, on):
        for b in self.tree.get_children():
            self.tree.item(b, open=on)

    # ---------- actions / report ----------
    def _build_actions(self):
        a = ttk.Frame(self)
        a.grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Button(a, text="Generate backup", command=self._generate).pack(side="left")
        ttk.Button(a, text="Export channel list (CSV)…", command=self._export).pack(side="left", padx=6)
        self.status = ttk.Label(a, text="")
        self.status.pack(side="left", padx=10)

    def _build_report(self):
        self.report = scrolledtext.ScrolledText(self, height=10, font=("Consolas", 9))
        self.report.grid(row=3, column=0, sticky="nsew", pady=4)

    def _fields(self):
        return dict(copy_name=self.var_name.get(), copy_tone=self.var_tone.get(),
                    copy_shift=self.var_shift.get(), copy_power=self.var_power.get(),
                    copy_skip=self.var_skip.get(), copy_narrow=self.var_narrow.get(),
                    op_mode=OpMode.FM, copy_tuning_step=False)

    def _generate(self):
        if not self.bank_order:
            messagebox.showwarning("No image", "Load an FT-60 image first.")
            return
        try:
            if not self.loaded_source_path or not same_path(self.var_img.get(), self.loaded_source_path):
                raise ValueError("Source path changed; load the image with Browse before generating")
            plan = self._plan()
            if plan.dropped:
                raise ValueError(f"Overflow: {len(plan.dropped)} channels exceed slot 999; reduce gaps or included banks")
            if os.path.exists(self.var_out.get()) and not messagebox.askyesno("Replace output", "Replace the existing output file?"):
                return
            report, dropped = cc.generate_plan(
                plan, self.var_tmpl.get(), self.var_out.get(),
                callsign=self.var_call.get().strip().upper(), source_path=self.loaded_source_path)
        except Exception as e:
            messagebox.showerror("Generate error", str(e))
            return
        self.last_report = report
        self.report.delete("1.0", "end")
        self.report.insert("end", f"Wrote {len(report)} channels -> {self.var_out.get()}\n")
        if dropped:
            self.report.insert("end", f"DROPPED {len(dropped)} past channel 999\n")
        last = None
        for r in report:
            lab = self.labels.get(r["bank"], r["bank"])
            if lab != last:
                self.report.insert("end", f"--- {lab} ---\n")
                last = lab
            self.report.insert("end", f"{r['target']:>4}  {r['name']:16s} {fmt.mhz_text(r['freq_hz'])}\n")
        self.status.config(text=f"Done: {len(report)} channels.")

    def _export(self):
        if not self.last_report:
            messagebox.showinfo("Export", "Generate a backup first, then export its channel list.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                         initialfile="channel_list.csv")
        if not p:
            return
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ch", "name", "freq_MHz", "bank_label", "ft60_ch"])
            for r in self.last_report:
                w.writerow([r["target"], r["name"], fmt.mhz_text(r['freq_hz']),
                            self.labels.get(r["bank"], r["bank"]), r["source"]])
        self.status.config(text=f"Exported -> {p}")


def main():
    root = tk.Tk()
    root.title("FT-60 → FTM-300DR converter")
    root.geometry("820x760")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
