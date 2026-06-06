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
├── dbg/
│   ├── __init__.py
│   └── __main__.py
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
dbg
```

Compatibility aliases:

```bash
dbgui
dioptas_batch_gui
dioptas-batch-gui
```

For a local checkout, you can also launch the app directly:

```bash
python -m dbg
```

or:

```bash
python -m dioptas_batch_gui
```

## Basic Workflow

1. Set **Watch Directory** or switch to **Batch Mode** and select files manually.
2. Choose the output mode:
   - **Auto** uses `<source folder>/processed-YYYY-MM-DD`.
   - **Existing directory** writes missing products into a selected processed output folder.
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
- `<base_name>-param/<base_name>.metadata.v1.json`

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
    ├── <base_name>.metadata.v1.json
    └── <calibration>.poni
```

If the selected output directory already exists, the app inspects the existing
products and writes only missing outputs when overwrite is disabled. Existing
CHI/XY/DAT/NPY products are left untouched. Missing HDF5 metadata exports are
added under the corresponding `*-param` folder. If an older metadata JSON file
is structurally compatible, missing top-level sections are added conservatively;
if compatibility is uncertain, a versioned metadata JSON file is written instead
of replacing the old file.

The metadata JSON uses `schema_version: "1.0"` and recursively records HDF5
file attributes, groups, datasets, dataset attributes, group attributes,
`NX_class` values, source paths, provenance, and a small canonical index for
common coordinates and detector/instrument/scan paths. Large datasets are
described by shape and dtype rather than duplicated inline.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
