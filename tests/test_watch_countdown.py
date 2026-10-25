from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

import dioptas_batch_gui.gui as gui_module


class _Settings:
    def __init__(self, *_args):
        pass

    def value(self, _key, default=None, **_kwargs):
        return default

    def setValue(self, _key, _value):
        pass

    def sync(self):
        pass


def test_watch_countdown_matches_idle_deadline_and_resets(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(gui_module, "QSettings", _Settings)
    app = QApplication.instance() or QApplication([])
    window = gui_module.DioptasBatchGUI()
    clock = {"now": 1000.0, "last_activity": 1000.0}
    monkeypatch.setattr(
        gui_module, "time", SimpleNamespace(time=lambda: clock["now"])
    )
    window.file_watcher = SimpleNamespace(
        get_last_activity_time=lambda: clock["last_activity"],
        get_completed_files=lambda: [],
        stop=lambda: None,
    )

    try:
        window.watch_idle_timeout_spin.setValue(2)
        assert window.watch_countdown_label.text() == "Auto-stop in: 00:02:00"

        clock["now"] = 1015.0
        window._check_for_files()
        assert window.watch_countdown_label.text() == "Auto-stop in: 00:01:45"

        clock["last_activity"] = 1015.0
        window._check_for_files()
        assert window.watch_countdown_label.text() == "Auto-stop in: 00:02:00"

        window.watch_idle_timeout_spin.setValue(1)
        assert window.watch_countdown_label.text() == "Auto-stop in: 00:01:00"

        clock["now"] = 1075.0
        window.processing_thread = object()
        window._check_for_files()
        assert window.watch_countdown_label.text() == "Auto-stop in: 00:00:00"
        assert window.file_watcher is not None

        window.processing_thread = None
        window._check_for_files()
        assert window.file_watcher is None
        assert window.watch_countdown_label.text() == "Auto-stop in: --:--:--"
    finally:
        window.processing_thread = None
        window.close()


def test_two_workers_becomes_default_once_and_opt_out_persists(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    saved = {"parallel_workers_two": False}

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
    first_window = gui_module.DioptasBatchGUI()
    assert first_window.parallel_workers_cb.isChecked()
    assert saved["parallel_workers_default_on_migrated"] is True

    first_window.parallel_workers_cb.setChecked(False)
    first_window.close()
    second_window = gui_module.DioptasBatchGUI()
    try:
        assert not second_window.parallel_workers_cb.isChecked()
    finally:
        second_window.close()
