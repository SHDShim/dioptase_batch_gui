"""Supported diffraction image file formats for Dioptas-backed processing."""

from __future__ import annotations

import re
from pathlib import Path


# Extensions explicitly selected for batch, sequence, and watch processing.
DIFFRACTION_IMAGE_EXTENSIONS = (
    ".tif",
    ".tiff",
    ".edf",
    ".cbf",
    ".h5",
    ".hdf",
    ".hdf5",
    ".nxs",
    ".img",
    ".sfrm",
    ".dm3",
    ".xml",
    ".kccd",
    ".msk",
    ".spr",
    ".mccd",
    ".mar3450",
    ".pnm",
)

HDF5_EXTENSIONS = (".h5", ".hdf", ".hdf5", ".nxs")


def has_supported_image_extension(path: str | Path) -> bool:
    """Return True when a path has one of the selected source-image extensions."""
    name = str(path).lower()
    return any(
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
    """Return the QFileDialog filter for selected diffraction image formats."""
    patterns = " ".join(f"*{extension}" for extension in DIFFRACTION_IMAGE_EXTENSIONS)
    return f"Dioptas Image Files ({patterns})"
