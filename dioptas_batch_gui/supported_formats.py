"""Supported diffraction image file formats for Dioptas-backed processing."""

from __future__ import annotations

import re
from pathlib import Path


# Dioptas ImgModel loads images through PIL, fabIO, Lambda, Karabo, and HDF5
# loaders. Keep this list extension-based for GUI filters and watch-mode
# discovery; manual "All Files" selection remains available for unusual files.
DIFFRACTION_IMAGE_EXTENSIONS = (
    ".h5",
    ".hdf",
    ".hdf5",
    ".nxs",
    ".tif",
    ".tiff",
    ".edf",
    ".cbf",
    ".mar3450",
    ".mar2300",
    ".mar2300.gz",
    ".marccd",
    ".mccd",
    ".img",
    ".sfrm",
    ".dm3",
    ".kcd",
    ".msk",
    ".spr",
    ".ge",
    ".pnm",
    ".pgm",
    ".pbm",
    ".fit2d",
    ".spe",
    ".mrc",
    ".npy",
    ".npz",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
)

HDF5_EXTENSIONS = (".h5", ".hdf", ".hdf5", ".nxs")
GENERATED_CAKE_SUFFIXES = (".int.cake.npy", ".tth.cake.npy", ".azi.cake.npy")


def has_supported_image_extension(path: str | Path) -> bool:
    """Return True for a Dioptas image, excluding this application's cake outputs."""
    name = str(path).lower()
    return not name.endswith(GENERATED_CAKE_SUFFIXES) and any(
        name.endswith(extension) for extension in DIFFRACTION_IMAGE_EXTENSIONS
    )


def has_hdf5_extension(path: str | Path) -> bool:
    """Return True when a path has a conventional HDF5/NeXus extension."""
    return Path(path).suffix.lower() in HDF5_EXTENSIONS


def image_file_regex() -> str:
    """Return a case-insensitive regex for supported image file paths."""
    alternatives = [
        re.escape(extension.lstrip("."))
        for extension in DIFFRACTION_IMAGE_EXTENSIONS
    ]
    return rf".*\.({'|'.join(alternatives)})$"


def qt_image_file_filter() -> str:
    """Return the QFileDialog filter string for Dioptas-readable image files."""
    patterns = " ".join(f"*{extension}" for extension in DIFFRACTION_IMAGE_EXTENSIONS)
    return f"Dioptas Image Files ({patterns});;All Files (*)"
