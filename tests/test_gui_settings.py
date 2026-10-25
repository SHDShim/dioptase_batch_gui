from pathlib import Path

from PyQt6.QtCore import QSettings as QtSettings
from PyQt6.QtWidgets import QApplication

import dioptas_batch_gui.gui as gui_module


def test_gui_state_restores_after_close(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    saved = {}

    class MemorySettings:
        def __init__(self, *_args):
            pass

        def value(self, key, default=None, **_kwargs):
            return saved.get(key, default)

        def setValue(self, key, value):
            saved[key] = value

        def sync(self):
            pass

    monkeypatch.setattr(gui_module, "QSettings", MemorySettings)
    app = QApplication.instance() or QApplication([])
    source = str(tmp_path / "scan_0001.h5")
    output = str(tmp_path / "processed")

    first = gui_module.DioptasBatchGUI()
    first.cal_file_edit.setText(str(tmp_path / "calibration.poni"))
    first.mask_file_edit.setText(str(tmp_path / "detector.mask"))
    first.watch_dir_edit.setText(str(tmp_path))
    first.watch_idle_timeout_spin.setValue(42)
    first.watch_stable_seconds_spin.setValue(23)
    first.export_chi_cb.setChecked(False)
    first.export_xy_cb.setChecked(True)
    first.export_dat_cb.setChecked(True)
    first.export_npy_cb.setChecked(False)
    first.export_metadata_cb.setChecked(False)
    first.apply_mask_to_chi_cb.setChecked(False)
    first.apply_mask_to_cake_cb.setChecked(True)
    first.overwrite_cb.setChecked(True)
    first.parallel_workers_cb.setChecked(False)
    first.integration_points_edit.setText("4756")
    first.mode_tabs.setCurrentIndex(1)
    first.sequence_nav_time_rb.setChecked(True)
    first.selected_files = [source]
    assert first._set_sequence_file(source)
    first.output_auto_cb.setChecked(False)
    first.output_dir_edit.setText(output)
    first.output_auto_cb.setChecked(True)
    first.output_auto_cb.setChecked(False)
    assert first.output_dir_edit.text() == output
    first.file_history_records = [{
        "path": source, "status": "processed", "completed_at": "2026-10-25 12:00"
    }]
    first._render_file_history()
    first.status_label.setText("Status: Sequence file processed")
    first.stats_label.setText("Sequence file: scan_0001 | Last batch: 4/4 images")
    first.progress_bar.setMaximum(4)
    first.progress_bar.setValue(4)
    first.close()

    second = gui_module.DioptasBatchGUI()
    try:
        assert second.cal_file_edit.text() == str(tmp_path / "calibration.poni")
        assert second.mask_file_edit.text() == str(tmp_path / "detector.mask")
        assert second.watch_dir_edit.text() == str(tmp_path)
        assert second.watch_idle_timeout_spin.value() == 42
        assert second.watch_stable_seconds_spin.value() == 23
        assert not second.export_chi_cb.isChecked()
        assert second.export_xy_cb.isChecked()
        assert second.export_dat_cb.isChecked()
        assert not second.export_npy_cb.isChecked()
        assert not second.export_metadata_cb.isChecked()
        assert not second.apply_mask_to_chi_cb.isChecked()
        assert second.apply_mask_to_cake_cb.isChecked()
        assert second.overwrite_cb.isChecked()
        assert not second.parallel_workers_cb.isChecked()
        assert second.integration_points_edit.text() == "4756"
        assert second.mode_tabs.currentIndex() == 1
        assert second.sequence_nav_time_rb.isChecked()
        assert second.selected_files == [source]
        assert second.sequence_file_path == Path(source)
        assert second.output_dir_edit.text() == output
        assert not second.output_auto_cb.isChecked()
        assert second.file_history_records == first.file_history_records
        assert second.file_list_table.rowCount() == 1
        assert second.status_label.text() == "Status: Sequence file processed"
        assert second.stats_label.text() == "Sequence file: scan_0001 | Last batch: 4/4 images"
        assert (second.progress_bar.value(), second.progress_bar.maximum()) == (4, 4)
        assert not second.watch_toggle_btn.isChecked()
        assert second.processing_thread is None
    finally:
        second.close()


def test_in_progress_status_restores_as_stopped(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    saved = {
        "last_status": "Status: Watching for files...",
        "progress_max": 20,
        "progress_value": 7,
        "active_tab": 2,
    }

    class MemorySettings:
        def __init__(self, *_args):
            pass

        def value(self, key, default=None, **_kwargs):
            return saved.get(key, default)

        def setValue(self, key, value):
            saved[key] = value

        def sync(self):
            pass

    monkeypatch.setattr(gui_module, "QSettings", MemorySettings)
    app = QApplication.instance() or QApplication([])
    window = gui_module.DioptasBatchGUI()
    try:
        assert window.mode_tabs.currentIndex() == 2
        assert window.status_label.text() == "Status: Stopped"
        assert window.progress_bar.value() == 0
        assert not window.watch_toggle_btn.isChecked()
        assert window.file_watcher is None
    finally:
        window.close()


def test_settings_survive_with_qt_ini_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    settings_path = tmp_path / "ui-settings.ini"
    monkeypatch.setattr(
        gui_module, "QSettings",
        lambda *_args: QtSettings(str(settings_path), QtSettings.Format.IniFormat),
    )
    app = QApplication.instance() or QApplication([])
    source = str(tmp_path / "scan_0002.h5")

    first = gui_module.DioptasBatchGUI()
    first.cal_file_edit.setText(str(tmp_path / "calibration.poni"))
    first.selected_files = [source]
    first.export_chi_cb.setChecked(False)
    first.overwrite_cb.setChecked(True)
    first.parallel_workers_cb.setChecked(False)
    first.mode_tabs.setCurrentIndex(0)
    first.close()

    assert settings_path.exists()
    second = gui_module.DioptasBatchGUI()
    try:
        assert second.cal_file_edit.text() == str(tmp_path / "calibration.poni")
        assert second.selected_files == [source]
        assert not second.export_chi_cb.isChecked()
        assert second.overwrite_cb.isChecked()
        assert not second.parallel_workers_cb.isChecked()
        assert second.process_batch_btn.isEnabled()
    finally:
        second.close()
