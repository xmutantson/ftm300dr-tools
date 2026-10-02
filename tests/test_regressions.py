"""Offline regressions. Synthetic byte arrays only; no CHIRP, serial, or radio."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import backup_io
import converter_core as cc
import ft60_reader
import ftm300dr_editor as editor
import ftm300dr_format as fmt
import ftm300dr_gui as gui
from ftm300dr_reader import read_channel, read_backup
from ftm300dr_writer import write_channel, write_backup, clear_channel
from neutral import NeutralChannel, Duplex, Mode, OpMode, Power, ToneMode


def blank():
    data = bytearray(b"\xa5" * fmt.FILE_SIZE)
    data[:6] = fmt.MAGIC
    for slot in range(1, 1000):
        clear_channel(data, slot)
    return data


def channel(**kwargs):
    values = dict(index=0, name="TEST", rx_freq_hz=146_520_625, tx_freq_hz=146_520_625)
    values.update(kwargs)
    return NeutralChannel(**values)


def populated(**kwargs):
    data = blank()
    write_channel(data, 1, channel(**kwargs))
    return data


def record(data, slot=1):
    start = fmt.mem_offset(slot)
    return bytes(data[start:start + fmt.REC_SIZE])


def dialog(data, original=None, **overrides):
    ch = original or channel(rx_freq_hz=146_520_000, tx_freq_hz=146_520_000, offset_hz=600_000)
    values = dict(slot=1, name=ch.name, freq=fmt.mhz_text(ch.rx_freq_hz),
                  tx=fmt.mhz_text(ch.tx_freq_hz), shift=ch.duplex.value,
                  offset=fmt.mhz_text(ch.offset_hz), tone=ch.tone_mode.value,
                  ctcss=str(ch.ctcss_tx_hz), dcs=str(ch.dtcs_code), pwr=ch.power.value,
                  skip=ch.skip, mode=ch.mode.value)
    values.update(overrides)
    obj = SimpleNamespace(master=SimpleNamespace(data=data), original=original,
                          used=set(), result=None, destroy=Mock())
    for key, value in values.items():
        setattr(obj, "v_" + key, Mock(get=Mock(return_value=value)))
    return obj


class RecordTests(unittest.TestCase):
    def test_name_only_preserves_tsql_dtcs_custom_offset_and_unknown_bytes(self):
        for tone in (ToneMode.TSQL, ToneMode.DTCS):
            with self.subTest(tone=tone):
                data = populated(tone_mode=tone, duplex=Duplex.PLUS,
                                 offset_hz=1_200_000, tx_freq_hz=147_720_625, skip="P")
                mo = fmt.mem_offset(1)
                for byte, value in ((0, 0xD1), (11, 0xA7), (12, 0x69), (14, 0x83), (15, 0x97)):
                    data[mo + byte] = value
                before = bytes(data)
                old = read_channel(data, 1)
                self.assertEqual(old.tx_freq_hz, 147_720_625)
                self.assertEqual(old.skip, "P")
                write_channel(data, 1, replace(old, name="NEW"))
                self.assertEqual(record(data), record(before))
                allowed = set(range(fmt.name_offset(1), fmt.name_offset(1) + 16))
                allowed.update(range(fmt.name_len_offset(1), fmt.name_len_offset(1) + 2))
                self.assertTrue(all(a == b or i in allowed for i, (a, b) in enumerate(zip(before, data))))

    def test_unknown_semantics_can_be_renamed(self):
        data = populated()
        mo = fmt.mem_offset(1)
        data[mo + 1] = 0x91
        data[mo + 5] = 0xF7
        data[mo + 9] = 0xFF
        data[mo] |= 0x60
        old = read_channel(data, 1)
        self.assertEqual(old.mode, Mode.UNKNOWN)
        self.assertEqual(old.duplex, Duplex.UNKNOWN)
        before = record(data)
        write_channel(data, 1, replace(old, name="OPAQUE"))
        self.assertEqual(record(data), before)
        with self.assertRaises(ValueError):
            write_channel(data, 1, replace(read_channel(data, 1), power=Power.LOW))

    def test_power_edit_preserves_every_other_record_bit(self):
        data = populated(tone_mode=ToneMode.DTCS, skip="P")
        mo = fmt.mem_offset(1)
        data[mo + 12:mo + 16] = b"\x12\x18\x34\x56"
        before = record(data)
        write_channel(data, 1, replace(read_channel(data, 1), power=Power.LOW))
        expected = bytearray(before)
        expected[9] = (expected[9] & 0x3F) | 0x80
        self.assertEqual(record(data), expected)

    def test_noop_preserves_entire_backup(self):
        data = populated()
        before = bytes(data)
        write_channel(data, 1, read_channel(data, 1))
        self.assertEqual(data, before)

    def test_rx_edit_preserves_inactive_split_offset_and_same_band_step(self):
        data = populated()
        mo = fmt.mem_offset(1)
        data[mo + 5] = 0x0B
        data[mo + 6:mo + 9] = b"\x14\x43\x56"
        data[mo + 13] = 42
        before = bytearray(record(data))
        old = read_channel(data, 1)
        write_channel(data, 1, replace(old, rx_freq_hz=146_521_250, tx_freq_hz=146_521_250))
        before[2:5] = bytes(fmt.freq_encode_bytes(146_521_250))
        self.assertEqual(record(data), before)

    def test_ctcss_edit_preserves_inactive_dcs_and_other_tone_bits(self):
        data = populated(tone_mode=ToneMode.TSQL)
        mo = fmt.mem_offset(1)
        data[mo + 10] = 0xE5
        before = bytearray(record(data))
        write_channel(data, 1, replace(read_channel(data, 1), ctcss_tx_hz=100.0, ctcss_rx_hz=100.0))
        before[9] = (before[9] & 0xC0) | fmt.CTCSS.index(100.0)
        self.assertEqual(record(data), before)

    def test_plus_minus_and_split_tx(self):
        for dup, tx in ((Duplex.PLUS, 147_720_625), (Duplex.MINUS, 145_320_625),
                        (Duplex.SPLIT, 446_006_250)):
            with self.subTest(duplex=dup):
                data = populated(duplex=dup, offset_hz=1_200_000, tx_freq_hz=tx)
                self.assertEqual(read_channel(data, 1).tx_freq_hz, tx)

    def test_unknown_extra_100_records_and_unrelated_bytes_survive_conversion(self):
        source = bytes(blank())
        out = write_backup(source, [channel()])
        changed_ranges = [
            (fmt.MEM_TABLE_BASE, fmt.mem_offset(1000)),
            (fmt.NAME_TABLE_BASE, fmt.name_offset(1000)),
            (fmt.NAME_LEN_BASE, fmt.name_len_offset(1000)),
        ]
        self.assertEqual(len(out), fmt.FILE_SIZE)
        self.assertTrue(all(a == b or any(lo <= i < hi for lo, hi in changed_ranges)
                            for i, (a, b) in enumerate(zip(source, out))))
        for offset, size in ((fmt.mem_offset(1000), 1600), (fmt.name_offset(1000), 1600),
                             (fmt.name_len_offset(1000), 200)):
            self.assertEqual(source[offset:offset + size], out[offset:offset + size])

    def test_invalid_slot_header_duplicate_and_name_leave_buffer_unchanged(self):
        data = populated()
        before = bytes(data)
        for slot in (0, -1, 1000, True):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                write_channel(data, slot, channel())
        with self.assertRaises(ValueError):
            write_backup(data, [channel(), channel()])
        with self.assertRaises(ValueError):
            write_channel(data, 1, replace(read_channel(data, 1), name="x" * 17))
        self.assertEqual(data, before)
        for bad in (bytes(fmt.FILE_SIZE), bytes(fmt.MAGIC), b"WRONG!" + before[6:]):
            with self.assertRaises(ValueError):
                write_backup(bad, [])
            with self.assertRaises(ValueError):
                read_backup(bad)

    def test_precise_decimal_frequency_roundtrip(self):
        for hz in (146_520_625, 146_521_250, 446_006_250):
            self.assertEqual(fmt.parse_mhz(fmt.mhz_text(hz)), hz)
            self.assertEqual(fmt.freq_decode(*fmt.freq_encode_bytes(hz)), hz)
        for text in ("146.520626", "146.5206251", "NaN", "Infinity", "-1", "0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                fmt.parse_mhz(text)

    def test_unsupported_encoding_rejected(self):
        cases = [
            dict(mode=Mode.AM), dict(op_mode=OpMode.AMS), dict(op_mode=OpMode.DN),
            dict(duplex=Duplex.OFF, tx_freq_hz=0), dict(tone_mode=ToneMode.CROSS),
            dict(tone_mode=ToneMode.TSQL, ctcss_rx_hz=100.0),
            dict(tone_mode=ToneMode.DTCS, dtcs_polarity="RN"),
            dict(tone_mode=ToneMode.DTCS, dtcs_code=999),
            dict(tone_mode=ToneMode.TONE, ctcss_tx_hz=88.6),
            dict(duplex=Duplex.PLUS, offset_hz=625, tx_freq_hz=146_521_250),
            dict(duplex=Duplex.PLUS, offset_hz=12_800_000, tx_freq_hz=159_320_625),
            dict(tx_freq_hz=145_000_000), dict(tuning_step_hz=5000),
            dict(rx_freq_hz=120_000_000, tx_freq_hz=120_000_000),
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fmt.encode_record(channel(**changes))


class SourceAndPlanTests(unittest.TestCase):
    def memory(self, **changes):
        values = dict(name="FT60", freq=146_520_000, duplex="", offset=600_000,
                      tuning_step=5.0, mode="FM", tmode="TSQL", rtone=100.0,
                      ctone=88.5, dtcs=23, dtcs_polarity="NN", power="High", skip="P", number=42)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_ft60_single_tone_contract(self):
        ch = ft60_reader.memory_to_neutral(self.memory(), 0)
        self.assertEqual((ch.ctcss_tx_hz, ch.ctcss_rx_hz), (100.0, 100.0))
        self.assertEqual(ch.skip, "P")
        fmt.encode_record(cc.apply_fields(ch))
        with self.assertRaises(ValueError):
            ft60_reader.memory_to_neutral(self.memory(tmode="TSQL-R"), 0)

    def test_unknown_source_vocabulary_rejected(self):
        for change in (dict(duplex="?"), dict(mode="?"), dict(tmode="?"), dict(skip="?")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ft60_reader.memory_to_neutral(self.memory(**change), 0)

    def test_deselect_shift_normalizes_tx_but_never_enables_receive_only(self):
        ch = channel(duplex=Duplex.PLUS, tx_freq_hz=147_120_625, offset_hz=600_000)
        out = cc.apply_fields(ch, copy_shift=False)
        self.assertEqual((out.duplex, out.offset_hz, out.tx_freq_hz), (Duplex.NONE, 0, out.rx_freq_hz))
        fmt.encode_record(out)
        with self.assertRaises(ValueError):
            cc.apply_fields(channel(duplex=Duplex.OFF, tx_freq_hz=0), copy_shift=False)
        self.assertEqual(cc.apply_fields(channel(mode=Mode.AM), copy_narrow=False).mode, Mode.AM)

    def test_unbanked_priority_membership_report_and_saved_channels_agree(self):
        channels = {1: channel(name="BANK"), 2: channel(name="FREE"), 3: channel(name="BOTH")}
        channels, banks, _ = cc.with_unbanked(channels, {"A": {1, 3}, "B": {3}}, ["A", "B"])
        plan = cc.build_plan(channels, banks, priority=[cc.UNBANKED, "B", "A"],
                             included={cc.UNBANKED, "B", "A"}, fields={}, include_unbanked=False, gap=1)
        self.assertEqual([(r["source"], r["target"]) for r in plan.report], [(2, 1), (3, 3), (1, 5)])
        with TemporaryDirectory() as directory:
            template, out = Path(directory) / "template.dat", Path(directory) / "out.dat"
            template.write_bytes(blank())
            report, dropped = cc.generate_plan(plan, template, out)
            actual = read_backup(out.read_bytes())
            self.assertEqual({r["target"]: r["name"] for r in report}, {s: c.name for s, c in actual.items()})
            self.assertFalse(dropped)

    def test_excluded_banks_do_not_leak_into_unbanked(self):
        channels = {1: channel(), 2: channel(), 3: channel()}
        layout = cc.assign_slots(channels, {"A": {1}, "B": {2}}, ["A", "B"], {"A"}, include_unbanked=True)
        self.assertEqual([r["source"] for r in layout], [1, 3])

    def test_overflow_and_empty_selection_fail_before_output(self):
        for start, included in ((999, {"A"}), (1, set())):
            plan = cc.build_plan({1: channel(), 2: channel()}, {"A": {1, 2}},
                                 priority=["A"], included=included, fields={}, start=start,
                                 include_unbanked=False)
            with patch.object(cc, "read_backup_file") as read, patch.object(cc, "save_backup") as save:
                with self.assertRaises(ValueError):
                    cc.generate_plan(plan, "template", "output")
                read.assert_not_called()
                save.assert_not_called()

    def test_invalid_layout_parameters(self):
        for opts in (dict(start=0), dict(start=1000), dict(gap=-1), dict(priority=["A", "A"]),
                     dict(included={"NOPE"})):
            args = dict(priority=["A"], included={"A"}, fields={})
            args.update(opts)
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                cc.build_plan({1: channel()}, {"A": {1}}, **args)

    def test_capability_error_identifies_source_and_target(self):
        plan = cc.build_plan({42: channel(mode=Mode.AM)}, {"A": {42}},
                             priority=["A"], included={"A"}, fields={})
        with self.assertRaisesRegex(ValueError, "Source channel 42 -> target 1"):
            cc.generate_plan(plan, "template", "output")


class SaveTests(unittest.TestCase):
    def test_atomic_save_verified_and_protects_source(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "out.dat"
            data = bytes(blank())
            backup_io.save_backup(target, data)
            self.assertEqual(target.read_bytes(), data)
            with self.assertRaises(ValueError):
                backup_io.save_backup(target, data, protected_paths=[target.parent / "." / target.name])
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_failure_keeps_destination_and_removes_temporary_file(self):
        for stage in ("fsync", "verify", "replace"):
            with self.subTest(stage=stage), TemporaryDirectory() as directory:
                target = Path(directory) / "out.dat"
                original = bytes(blank())
                target.write_bytes(original)
                new = bytes(populated())
                if stage == "verify":
                    context = patch.object(backup_io, "read_backup_file", return_value=original)
                else:
                    context = patch.object(backup_io.os, stage, side_effect=OSError("injected failure"))
                with context, self.assertRaises(OSError):
                    backup_io.save_backup(target, new)
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_converter_cannot_overwrite_template_or_source(self):
        plan = cc.build_plan({1: channel()}, {"A": {1}}, priority=["A"], included={"A"}, fields={})
        with TemporaryDirectory() as directory:
            template, source = Path(directory) / "template.dat", Path(directory) / "source.img"
            template.write_bytes(blank())
            source.write_bytes(b"source-image")
            for target in (template, source):
                before = target.read_bytes()
                with self.assertRaises(ValueError):
                    cc.generate_plan(plan, template, target, source_path=source)
                self.assertEqual(target.read_bytes(), before)


class EditorTests(unittest.TestCase):
    def test_dialog_name_edit_preserves_full_model_and_record(self):
        for tone in (ToneMode.TSQL, ToneMode.DTCS):
            with self.subTest(tone=tone):
                data = populated(tone_mode=tone, duplex=Duplex.MINUS, tx_freq_hz=145_320_625,
                                 offset_hz=1_200_000, skip="P")
                old = read_channel(data, 1)
                dlg = dialog(data, old, name="RENAMED")
                with patch.object(editor.messagebox, "showerror") as error:
                    editor.ChannelDialog._ok(dlg)
                    error.assert_not_called()
                self.assertEqual(dlg.result[1], replace(old, name="RENAMED"))
                before = record(data)
                write_channel(data, *dlg.result)
                self.assertEqual(record(data), before)

    def test_dialog_offered_minus_and_occupied_slot(self):
        self.assertIn("-", editor.SHIFTS)
        data = blank()
        dlg = dialog(data, shift=next(k for k, v in editor.SHIFTS.items() if v == Duplex.MINUS))
        with patch.object(editor.messagebox, "showerror") as error:
            editor.ChannelDialog._ok(dlg)
            error.assert_not_called()
        self.assertEqual(dlg.result[1].tx_freq_hz, 145_920_000)
        dlg = dialog(data)
        dlg.used = {1}
        with patch.object(editor.messagebox, "showerror") as error:
            editor.ChannelDialog._ok(dlg)
            error.assert_called_once()
        self.assertIsNone(dlg.result)

    def test_full_backup_has_no_add_dialog(self):
        obj = SimpleNamespace(data=blank())
        with patch.object(editor, "read_backup", return_value=dict.fromkeys(range(1, 1000))), \
             patch.object(editor, "ChannelDialog") as create, patch.object(editor.messagebox, "showinfo"):
            editor.Editor.add(obj)
            create.assert_not_called()

    def test_invalid_load_leaves_session_unchanged(self):
        obj = SimpleNamespace(data=populated(), path="old.dat", source_path="old.dat",
                              dirty=True, _refresh=Mock())
        before = bytes(obj.data)
        with patch.object(editor, "read_backup_file", side_effect=ValueError("bad header")), \
             patch.object(editor.messagebox, "showerror"):
            editor.Editor._load(obj, "bad.dat")
        self.assertEqual((bytes(obj.data), obj.path, obj.source_path, obj.dirty), (before, "old.dat", "old.dat", True))
        obj._refresh.assert_not_called()

    def test_save_failure_retains_dirty_state_and_paths(self):
        obj = SimpleNamespace(data=populated(), path="old.dat", source_path="original.dat",
                              dirty=True, _refresh=Mock())
        with patch.object(editor.filedialog, "asksaveasfilename", return_value="new.dat"), \
             patch.object(editor, "save_backup", side_effect=OSError("disk")), \
             patch.object(editor.messagebox, "showerror"):
            self.assertFalse(editor.Editor.save_as(obj))
        self.assertTrue(obj.dirty)
        self.assertEqual(obj.path, "old.dat")
        self.assertEqual(obj.source_path, "original.dat")
        obj._refresh.assert_not_called()

    def test_dirty_prompt_cancel_discard_and_failed_save(self):
        obj = SimpleNamespace(dirty=True, save_as=Mock(return_value=False))
        for answer, expected in ((None, False), (False, True), (True, False)):
            with patch.object(editor.messagebox, "askyesnocancel", return_value=answer):
                self.assertEqual(editor.Editor._may_discard(obj), expected)

    def test_close_and_open_cancel_retain_session(self):
        obj = SimpleNamespace(_may_discard=Mock(return_value=False), master=Mock(), _load=Mock())
        with patch.object(editor.filedialog, "askopenfilename") as choose:
            editor.Editor.open(obj)
            choose.assert_not_called()
        editor.Editor.close(obj)
        obj.master.destroy.assert_not_called()


class GuiTests(unittest.TestCase):
    def test_invalid_plan_keeps_existing_tree(self):
        obj = SimpleNamespace(bank_order=["A"], tree=Mock(), status=Mock(),
                              _plan=Mock(side_effect=ValueError("invalid gap")))
        gui.App._refresh_tree(obj)
        obj.tree.delete.assert_not_called()
        obj.status.config.assert_called_once()

    def test_changed_source_path_blocks_generation(self):
        obj = SimpleNamespace(bank_order=["A"], loaded_source_path="old.img",
                              var_img=Mock(get=Mock(return_value="different.img")))
        with patch.object(gui.messagebox, "showerror") as error, patch.object(cc, "generate_plan") as generate:
            gui.App._generate(obj)
            error.assert_called_once()
            generate.assert_not_called()

    def test_failed_source_load_preserves_snapshot_and_restores_path(self):
        variable = Mock(get=Mock(return_value="bad.img"))
        obj = SimpleNamespace(var_img=variable, loaded_source_path="good.img",
                              channels={1: channel()}, bank_members={"A": {1}}, bank_order=["A"])
        with patch.object(cc, "load_source", side_effect=ValueError("bad image")), \
             patch.object(gui.messagebox, "showerror"):
            gui.App._load_image(obj)
        variable.set.assert_called_once_with("good.img")
        self.assertEqual(obj.bank_order, ["A"])
        self.assertEqual(set(obj.channels), {1})


if __name__ == "__main__":
    unittest.main()
