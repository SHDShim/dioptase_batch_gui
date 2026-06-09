# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.5.2] - 2026-06-09

- Fixed CAKE skip validation so existing arrays must match the image-derived resolution.
- Blocked runs with no selected output products.
- Prevented watch inactivity auto-stop during active processing.
- Fixed progress accounting for failed or cancelled image processing.

## [0.5.1] - 2026-06-06

- Stopped watch-mode queue processing when **Stop Watching** is pressed.
- Added cancellation handling so active watch processing stops after the current image finishes.
- Marked cancelled watch files in the file-history list.

## [0.5.0] - 2026-06-06

- Added selectable output directories, including incremental updates to existing processed folders.
- Added schema-versioned recursive HDF5 metadata export under each `*-param` folder.
- Preserved existing processed outputs by default while filling missing metadata products.
- Added tests for selected output directories, metadata creation, additive updates, and non-overwrite behavior.

## [0.4.2] - 2026-06-06

- Added `dbg` as the preferred short command and `python -m dbg` launcher while preserving existing entry points.
- Highlighted the latest processed file in the file-history list.
- Improved batch and watch-mode control layout and status-log visibility.

## [0.4.1] - 2026-06-06

- Fixed cumulative batch progress for multiple snapshot HDF5/NXS file sets.
- Simplified progress, tab, and process button labels.

## [0.1.0] - 2026-06-05

- Inserted snapshot numbers before trailing scan/index segments in output names.

## [0.0.9] - 2026-06-04

- Added snapshot-specific output naming for multi-image HDF5/NXS files.

## [0.0.8] - 2026-05-13

- Updated NPY cake output labeling.

## [0.0.7a] - 2026-03-25

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
