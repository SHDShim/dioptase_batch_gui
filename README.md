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
pip install dioptas-batch-gui
```

## Update to the latest PyPI release

```bash
pip install --upgrade dioptas-batch-gui
```

## Force reinstall from PyPI

```bash
pip install --upgrade --force-reinstall dioptas-batch-gui
```

## Verify Dependencies

```bash
python check_dependencies.py
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

For a local checkout, you can also launch the app directly:

```bash
python -m dioptas_batch_gui
```

## Basic Workflow

1. Set **Watch Directory** or switch to **Batch Mode** and select files manually.
2. Set **Output Directory**.
3. Select the **Calibration File** (`.poni`).
4. Optionally select a **Mask File**.
5. Configure integration points and azimuth bins.
6. Choose the export options you want.
7. Click **Start Watching** for automatic mode or **Process** for manual batch mode.
8. Click **Stop Watching** when finished with auto-processing.

## Output

For each processed dataset, the app exports:

- `<base_name>.chi`
- `<base_name>-param/<base_name>.int.cake.npy`
- `<base_name>-param/<base_name>.tth.cake.npy`
- `<base_name>-param/<base_name>.azi.cake.npy`

For HDF5/NXS files containing multiple snapshot images, outputs use a
one-based snapshot suffix in the output stem and parameter directory name.
When the input stem ends in a numeric scan/index segment, the snapshot suffix
is inserted before that final segment:

- `xxx_map_1_0001.h5` snapshot 1: `xxx_map_1_001_0001.chi`
- `xxx_map_1_0001.h5` snapshot 2: `xxx_map_1_002_0001.chi`
- `xxx_map_1_001_0001-param/xxx_map_1_001_0001.int.cake.npy`

Output layout:

```text
output_directory/
├── <base_name>.chi
└── <base_name>-param/
    ├── <base_name>.int.cake.npy
    ├── <base_name>.tth.cake.npy
    ├── <base_name>.azi.cake.npy
    └── <calibration>.poni
```

## License

GPL-3.0-only. See [LICENSE](LICENSE).
