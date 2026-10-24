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
