# Quick Start

## 1. Check Dependencies

```bash
python check_dependencies.py
```

## 2. Launch the GUI

```bash
python -m dioptas_batch_gui
```

After `pip install -e .` (or `pip install .`), you can also launch from any directory:

```bash
dbgui
```

## 3. Configure

1. Set **Watch Directory** (or switch to Batch Mode and pick files manually).
2. Set **Output Directory**.
3. Select **Calibration File** (`.poni`).
4. Optionally select **Mask File**.
5. Configure integration points and azimuth bins.
6. Choose CHI/NPY export options.

## 4. Process

- Click **Start Watching** for automatic mode, or
- Click **Process Selected Files** in batch mode.

## 5. Stop

Click **Stop Watching** when finished.

## Output Files

```text
output_directory/
├── <base_name>.chi
└── <base_name>-param/
    ├── <base_name>.int.cake.npy
    ├── <base_name>.tth.cake.npy
    ├── <base_name>.azi.cake.npy
    └── <calibration>.poni
```
