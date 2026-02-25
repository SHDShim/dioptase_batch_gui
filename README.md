# Dioptas Batch Processor GUI

A standalone GUI application for automated batch processing of Lambda detector X-ray diffraction data using Dioptas. Features automatic folder watching and exports to CHI (1D patterns) and NPY (2D cake images) formats.

## Features

- **Automatic Folder Watching**: Monitors a directory for new Lambda detector files (.nxs)
- **Automated Processing**: Processes files automatically as they appear
- **Dual Output Formats**:
  - CHI files: Standard 2-column text format for 1D diffraction patterns
  - NPY files: Compressed numpy archives with 2D cake images (intensity, 2θ, azimuth)
- **Real-time Progress**: Live status updates and processing logs
- **Configurable Integration**: Adjustable integration points and azimuth bins
- **Mask Support**: Optional mask file support
- **Background Processing**: Non-blocking GUI with threaded processing

## Requirements

This application requires a working Dioptas installation. It uses Dioptas as a Python library.

### Dependencies
- dioptas (with all its dependencies)
- PyQt6
- watchdog
- numpy
- h5py

## Installation

### 1. Install Dioptas

First, ensure Dioptas is installed in your conda environment. From the Dioptas source directory:

```bash
cd "/Users/danshim/ASU Dropbox/Sang-Heon Shim/Python/Dioptas-2026-01-10"
pip install -e .
```

### 2. Install Additional Dependencies

The main additional dependency is `watchdog` for file system monitoring:

```bash
pip install watchdog
```

Check if you need any other packages:

```bash
python -c "import PyQt6; print('PyQt6 OK')"
python -c "import watchdog; print('watchdog OK')"
python -c "import dioptas; print('Dioptas OK')"
```

## Usage

### Running the GUI

```bash
cd "/Users/danshim/ASU Dropbox/Sang-Heon Shim/Python/dioptas_batch_gui"
python batch_gui.py
```

### Configuration Steps

1. **Watch Directory**: Select the folder to monitor for new files
2. **Output Directory**: Choose where to save processed files
3. **Calibration File**: Select your .poni calibration file (created with Dioptas)
4. **Mask File** (optional): Select a mask file if needed
5. **Integration Points**: Set number of bins for 1D patterns (default: 2048)
6. **Azimuth Bins**: Set number of bins for 2D cakes (default: 360)
7. **Export Options**: 
   - ☑ Export CHI files (1D patterns)
   - ☑ Export NPY files (2D cakes)

### Starting Auto-Processing

1. Configure all settings
2. Click **"Start Auto-Processing"**
3. The application will monitor the watch directory
4. New files will be automatically processed as they appear
5. Click **"Stop Auto-Processing"** when done

## Output File Formats

### CHI Files (.chi)

Standard Dioptas CHI format with header:
```
# 2-theta (degrees) vs Intensity
# Calibration: <calibration_file>
<2theta_value> <intensity_value>
...
```

### NPY Files (.npz)

Compressed numpy archive containing:
- `intensity`: 2D array of cake image intensities
- `tth`: 1D array of 2-theta values (degrees)
- `azi`: 1D array of azimuth values (degrees)

Load with:
```python
import numpy as np
data = np.load('filename_cake.npz')
intensity = data['intensity']
tth = data['tth']
azi = data['azi']
```

## File Naming Convention

For a Lambda detector file set:
```
sample_001_m1.nxs
sample_001_m2.nxs
sample_001_m3.nxs
```

Outputs will be:
```
sample_001_0000.chi         # First image, 1D pattern
sample_001_0000_cake.npz    # First image, 2D cake
sample_001_0001.chi         # Second image, 1D pattern
sample_001_0001_cake.npz    # Second image, 2D cake
...
```

## Command-Line Usage

### Test File Watcher

```bash
python file_watcher.py /path/to/watch/directory
```

### Test Batch Processor

```bash
python batch_processor.py calibration.poni /input/directory /output/directory
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'dioptas'"

Solution: Install Dioptas first (see Installation section)

### "No module named 'watchdog'"

Solution: Install watchdog with `pip install watchdog`

### Files not being detected

- Ensure the watch directory contains .nxs files with Lambda naming pattern (`*_m[1-3]*.nxs`)
- Check that all 3 files (m1, m2, m3) are present for each dataset
- Files must finish writing (2-second delay after last modification)

### Processing errors

- Verify calibration file is valid (.poni format)
- Ensure input files are readable Lambda detector format
- Check output directory is writable
- Review log console for detailed error messages

## Architecture

```
dioptas_batch_gui/
├── batch_gui.py          # Main GUI application (PyQt6)
├── file_watcher.py       # Folder monitoring (watchdog)
├── batch_processor.py    # Integration engine (Dioptas)
└── README.md            # This file
```

### Key Components

- **FileWatcher**: Monitors directory using watchdog, handles file completion detection
- **BatchProcessor**: Uses Dioptas Configuration API for integration and export
- **DioptasBatchGUI**: PyQt6 interface with threaded processing
- **ProcessingThread**: Background worker thread for non-blocking processing

## Technical Notes

### Lambda Detector Files

Lambda detectors produce 3 files per acquisition (one per module):
- `*_m1.nxs`: Module 1
- `*_m2.nxs`: Module 2  
- `*_m3.nxs`: Module 3

The batch processor automatically groups these and loads them using Dioptas' LambdaLoader.

### Integration Process

1. Load Lambda image using LambdaLoader
2. Apply calibration from .poni file
3. Apply mask (if provided)
4. Perform 1D integration → CHI file
5. Perform 2D integration → Cake NPY file

### Performance

- Processing is multi-threaded (GUI remains responsive)
- One file set processed at a time
- Typical speed: 0.1-1 second per image (depends on size and CPU)

## Development

This project is independent of the Dioptas source tree and only imports Dioptas as a library.

To modify:
1. Edit the Python files in `dioptas_batch_gui/`
2. No need to rebuild Dioptas
3. Simply restart the GUI application

## License

This GUI wrapper follows the same GPL-3.0 license as Dioptas.

## Credits

Built on top of [Dioptas](https://github.com/Dioptas/Dioptas) by Clemens Prescher and contributors.

File watching powered by [watchdog](https://github.com/gorakhargosh/watchdog).

## Support

For issues with:
- **This GUI wrapper**: Check the log console and README troubleshooting
- **Dioptas integration**: Refer to [Dioptas documentation](https://dioptas.readthedocs.io/)
- **Lambda detector files**: Consult detector documentation

---

**Version**: 1.0.0  
**Author**: Created for automated XRD data processing  
**Date**: 2026-01-10
