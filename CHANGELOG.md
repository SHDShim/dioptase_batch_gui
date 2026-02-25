# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

- Removed root-level compatibility launchers (`batch_gui.py`, `batch_processor.py`, `file_watcher.py`).
- Standardized execution to package entry points only (`dbgui` or `python -m dioptas_batch_gui`).

## [1.0.0] - 2026-02-25

- Restructured project into a proper Python package (`dioptas_batch_gui/`).
- Added `dioptas_batch_gui/version.py` as the single version source.
- Added repository standard files for GitHub submissions.
- Added packaging metadata (`pyproject.toml`) and runtime requirements (`requirements.txt`).
- Added compatibility launchers (`batch_gui.py`, `batch_processor.py`, `file_watcher.py`).
