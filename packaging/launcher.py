"""Entry point used by the standalone application builds."""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dioptas_batch_gui.version import __version__


def main() -> None:
    """Launch the GUI or print a version for packaged-build smoke tests."""
    multiprocessing.freeze_support()

    if "--version" in sys.argv[1:]:
        if sys.stdout is not None:
            print(f"Dioptas Batch GUI {__version__}")
        return

    if "--smoke-test" in sys.argv[1:]:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from dioptas_batch_gui.gui import DioptasBatchGUI

        app = QApplication([sys.argv[0]])
        window = DioptasBatchGUI()
        window.close()
        app.quit()
        if sys.stdout is not None:
            print(f"Dioptas Batch GUI {__version__} smoke test passed")
        return

    from dioptas_batch_gui.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
