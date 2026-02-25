# Quick Start Guide

## 1. Check Dependencies

```bash
cd "/Users/danshim/ASU Dropbox/Sang-Heon Shim/Python/dioptas_batch_gui"
python check_dependencies.py
```

If all dependencies are installed, proceed to step 2.

## 2. Launch the GUI

```bash
python batch_gui.py
```

## 3. Configure Settings

1. **Watch Directory**: Browse and select the folder where Lambda detector files will appear
2. **Output Directory**: Browse and select where to save the processed CHI and NPY files
3. **Calibration File**: Browse and select your .poni calibration file
4. **Mask File** (optional): Select a mask file if you have one
5. Adjust integration points and azimuth bins if needed (defaults are usually fine)
6. Ensure both CHI and NPY export options are checked

## 4. Start Auto-Processing

Click the **"Start Auto-Processing"** button. The GUI will:
- Monitor the watch directory for new .nxs files
- Automatically detect when Lambda files (m1, m2, m3) are complete
- Process each image and export CHI and NPY files
- Show progress in real-time
- Log all activities

## 5. Stop When Done

Click **"Stop Auto-Processing"** when you're finished.

## Example Workflow

```bash
# Terminal 1: Start the GUI
cd "/Users/danshim/ASU Dropbox/Sang-Heon Shim/Python/dioptas_batch_gui"
python batch_gui.py

# Terminal 2: Copy files to watch directory (or they arrive automatically)
cp /source/path/*.nxs /watch/directory/

# The GUI will automatically process them!
```

## Output Files

For each Lambda file set `sample_001_m[1-3].nxs` with N images:

```
output_directory/
├── sample_001_0000.chi          # Image 0, 1D pattern
├── sample_001_0000_cake.npz     # Image 0, 2D cake
├── sample_001_0001.chi          # Image 1, 1D pattern
├── sample_001_0001_cake.npz     # Image 1, 2D cake
...
├── sample_001_NNNN.chi          # Image N, 1D pattern
└── sample_001_NNNN_cake.npz     # Image N, 2D cake
```

## Reading NPY Files in Python

```python
import numpy as np

# Load the cake data
data = np.load('sample_001_0000_cake.npz')
intensity = data['intensity']  # 2D array (azimuth, 2theta)
tth = data['tth']              # 1D array of 2-theta values
azi = data['azi']              # 1D array of azimuth values

# Plot with matplotlib
import matplotlib.pyplot as plt
plt.imshow(intensity, aspect='auto', extent=[tth.min(), tth.max(), azi.min(), azi.max()])
plt.xlabel('2θ (degrees)')
plt.ylabel('Azimuth (degrees)')
plt.colorbar(label='Intensity')
plt.show()
```

## Troubleshooting

**Problem**: GUI doesn't start  
**Solution**: Run `python check_dependencies.py` to verify all packages are installed

**Problem**: Files aren't being detected  
**Solution**: Ensure files match the Lambda pattern `*_m[1-3]*.nxs` and all 3 modules are present

**Problem**: Processing fails  
**Solution**: Check the log console in the GUI for detailed error messages

---

For more details, see the full README.md
