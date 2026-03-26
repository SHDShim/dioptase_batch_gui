# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.0.7] - 2026-03-25

- Fixed a `QThread` lifecycle crash that could abort large batch runs partway through processing.
- Replaced the modal "files already exist" warning with non-blocking processing-log entries.
- Added color-coded file-history and processing-log status for pending, skipped, processed, and overwritten files.
- Added a file-list legend explaining the row color and font meanings.

## [0.0.6] - 2026-03-23

- Removed root-level compatibility launchers (`batch_gui.py`, `batch_processor.py`, `file_watcher.py`).
- Standardized execution to package entry points only (`dbgui` or `python -m dioptas_batch_gui`).

## [1.0.0] - 2026-02-25

- Restructured project into a proper Python package (`dioptas_batch_gui/`).
- Added `dioptas_batch_gui/version.py` as the single version source.
- Added repository standard files for GitHub submissions.
- Added packaging metadata (`pyproject.toml`) and runtime requirements (`requirements.txt`).
- Added compatibility launchers (`batch_gui.py`, `batch_processor.py`, `file_watcher.py`).
