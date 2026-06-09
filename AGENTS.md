# AGENTS.md

## Project Purpose

`dioptas_batch_gui` is a Python GUI application for reproducible batch processing of synchrotron diffraction image data with Dioptas.

The app is intended to support high-pressure mineral physics and related beamline workflows where many `.h5` or `.nxs` detector files must be converted consistently into analysis-ready products.

## Primary Goals

- Provide a clear PyQt-based interface for Dioptas batch processing.
- Support three operation modes:
  - Batch mode for selected files.
  - Sequence mode for numbered file navigation and processing.
  - Watch mode for automatic processing of incoming files.
- Convert source detector files into selected output products:
  - 1D patterns: CHI, XY, DAT.
  - 2D cake arrays: NPY intensity, two-theta, and azimuth arrays.
  - HDF5 source metadata JSON exports.
- Preserve existing processed outputs by default.
- When overwrite is disabled, create only missing files from the checked output list.
- When overwrite is enabled, overwrite existing files only for the checked output list.
- Keep metadata export schema-versioned and reproducible.
- Maintain behavior suitable for scientific data processing: explicit file paths, conservative overwrites, clear logs, and testable processing logic.

## Environment

Use the `dev26a` conda environment for development, testing, and local execution unless the user explicitly requests another environment.

Preferred command pattern:

```zsh
conda activate dev26a
python -m pytest
python -m dioptas_batch_gui
```

If running commands non-interactively from an LLM or automation context, prefer:

```zsh
conda run -n dev26a python -m pytest
conda run -n dev26a python -m dioptas_batch_gui
```

## Development Guidance

- Use Python scientific-computing conventions and keep changes compatible with NumPy-oriented workflows.
- Prefer focused, minimal changes that preserve existing GUI behavior unless a user request explicitly changes it.
- Keep processor logic centralized in `dioptas_batch_gui/batch_processor.py` when behavior should apply to all modes.
- Keep GUI state, checkboxes, saved settings, and mode-specific controls in `dioptas_batch_gui/gui.py`.
- Add or update tests under `tests/` for changes to overwrite behavior, output selection, metadata export, and file-set processing.
- Avoid destructive file operations. Existing processed data should not be replaced unless overwrite behavior is explicitly enabled and selected.

## Verification

Before considering a change complete, run the most focused relevant tests in the `dev26a` environment.

For broad verification:

```zsh
conda run -n dev26a python -m pytest
conda run -n dev26a python -m py_compile dioptas_batch_gui/gui.py dioptas_batch_gui/batch_processor.py
```

If tests cannot be run, report the reason clearly.
