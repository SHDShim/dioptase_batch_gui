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
├── check_dependencies.py
├── pyproject.toml
├── requirements.txt
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
└── SECURITY.md
```

## Requirements

- Python 3.10+
- conda (recommended for environment management)

## Installation (Recommended)

Set up in this order:

1. Create and activate a conda environment named `dioptas`.

```bash
conda create -n dioptas python=3.10 -y
```

```
conda activate dioptas
```

2. Install Dioptas first inside that environment.

```bash
pip install dioptas
```

3. Install this package.

```bash
pip install dioptas_batch_gui
```


## Usage

Installed CLI commands (work from any directory once your environment is active in terminal or console):

After:

```bash
conda activate dioptas
```

```bash
dbgui
```
or

```
dioptas_batch_gui
```

or

```
dioptas-batch-gui
```

## Output

For each processed dataset, the app exports:

- `<base_name>.chi`
- `<base_name>-param/<base_name>.int.cake.npy`
- `<base_name>-param/<base_name>.tth.cake.npy`
- `<base_name>-param/<base_name>.azi.cake.npy`

## License

GPL-3.0-only. See [LICENSE](LICENSE).
