"""Single source of truth for package version."""

__version__ = "0.5.2"

"""
0.5.2 Fix CAKE skip validation, output selection validation, watch inactivity, and progress accounting.
0.5.1 Stop watch-mode queue processing when Stop Watching is pressed.
0.5.0 Add selected output directories and incremental HDF5 metadata exports.
0.4.2 Add dbg launcher, latest-file highlighting, and GUI/log visibility improvements.
0.4.1 Fix batch progress for multiple snapshot files and simplify progress/tab/button labels.
0.4.0 Add configurable watch-mode file-settle and auto-stop timeouts, with HDF5 stabilization checks before processing.
0.2.0 Add batch abort controls, source-local dated output folders, and darker button styles.
0.1.0 Insert snapshot numbers before trailing scan/index segments in output names.
0.0.9 Add snapshot-specific output naming for multi-image HDF5/NXS files.
0.0.8 Label change for npy to cake
0.0.7a Alpha build for TestPyPI with crash fix and skip/overwrite status visibility improvements.
0.0.6 GUI improvement
0.0.5 fix resolution of cake along theta axis.  it is adjusted to show twice more in cake than chi for twotheta
0.0.4 Include XY and DAT output options
0.0.3 Improve logical flow for overwrite
0.0.2 Initial version uploaded to pip
"""
