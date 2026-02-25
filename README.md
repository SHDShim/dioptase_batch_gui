# Dioptas Batch Processor GUI

Standalone GUI for automated batch processing of Lambda detector diffraction files using Dioptas.

## Features

- Folder watch mode for automatic processing of incoming `.nxs` / `.h5` files
- Manual batch mode for selected files
- CHI export (1D integration)
- NPY export (2D cake arrays: intensity, two-theta, azimuth)
- Optional mask support
- Background processing thread to keep GUI responsive

## Project Structure

```text
dioptas_batch_gui/
├── dioptas_batch_gui/
│   ├── __init__.py
│   ├── __main__.py
│   ├── version.py
│   ├── gui.py
│   ├── batch_processor.py
│   └── file_watcher.py
├── batch_gui.py           # Compatibility launcher
├── batch_processor.py     # Compatibility launcher
├── file_watcher.py        # Compatibility launcher
├── check_dependencies.py
├── pyproject.toml
├── requirements.txt
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── SECURITY.md
```

## Requirements

- Python 3.10+
- Dioptas
- PyQt6
- watchdog
- numpy
- h5py

## Installation

```bash
pip install -e .
```

If Dioptas is not already installed in your environment, install it first.

## Usage

Run dependency checks:

```bash
python check_dependencies.py
```

Launch GUI (recommended):

```bash
python -m dioptas_batch_gui
```

Installed CLI commands (work from any directory once your environment is active):

```bash
dbgui
# or
dioptas_batch_gui
# or
dioptas-batch-gui
```

Compatibility launch command from repo root:

```bash
python batch_gui.py
```

## Output

For each processed dataset, the app exports:

- `<base_name>.chi`
- `<base_name>-param/<base_name>.int.cake.npy`
- `<base_name>-param/<base_name>.tth.cake.npy`
- `<base_name>-param/<base_name>.azi.cake.npy`

## License

GPL-3.0-only. See [LICENSE](LICENSE).
