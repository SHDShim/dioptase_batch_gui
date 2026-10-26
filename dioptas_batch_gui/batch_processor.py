#!/usr/bin/env python
"""
Batch Processor Module for Dioptas Integration
Processes Lambda detector files and exports to CHI/XY/DAT and NPY formats.
"""

import os
import re
import logging
import multiprocessing
import queue
import shutil
import time
import uuid
import numpy as np
import json
from pathlib import Path
from glob import glob
from datetime import datetime, timezone
from typing import Any, Callable, List, Tuple, Optional
import h5py

# Dioptas imports
from dioptas.model.Configuration import Configuration
from dioptas.model.loader import FabioLoader, LambdaLoader

from .supported_formats import (
    DIFFRACTION_IMAGE_EXTENSIONS,
    has_hdf5_extension,
    has_supported_image_extension,
)

logger = logging.getLogger(__name__)

METADATA_SCHEMA_VERSION = "1.0"
METADATA_FILE_SUFFIX = ".metadata.v1.json"
MAX_INLINE_DATASET_ITEMS = 10000
ABORT_WORKER_GRACE_SECONDS = 2.0


def conservative_worker_limit() -> int:
    """Reserve CPU and memory for other applications during diffraction processing."""
    cpu_limit = max(1, (os.cpu_count() or 1) // 2)
    try:
        physical_bytes = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        memory_limit = max(1, physical_bytes // (8 * 1024**3))
    except (AttributeError, OSError, ValueError):
        memory_limit = 2
    return min(3, cpu_limit, memory_limit)


def _empty_file_stats(total_images=0) -> dict:
    """Return a fresh per-file statistics record."""
    return {
        'total_images': total_images,
        'processed': 0,
        'failed': 0,
        'failed_indices': [],
        'skipped': 0,
        'overwritten': 0,
        'chi_files': [],
        'xy_files': [],
        'dat_files': [],
        'npy_files': [],
        'metadata_files': [],
        'metadata_created': 0,
        'metadata_updated': 0,
        'metadata_versioned': 0,
        'cancelled': False,
    }


def _parallel_file_worker(config_kwargs, file_set, image_indices, options, messages, stop_event):
    """Run one contiguous frame range with a process-local Dioptas configuration."""
    handler = logging.Handler()
    handler.emit = lambda record: messages.put(
        ("log", (record.levelno, record.getMessage()))
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    try:
        processor = BatchProcessor(**config_kwargs)
        stats = processor.process_file_set(
            file_set,
            **options,
            image_indices=image_indices,
            progress_callback=lambda current, total, message: messages.put(("progress", message)),
            estimate_callback=lambda points: messages.put(("estimate", points)),
            should_continue=lambda: not stop_event.is_set(),
        )
        messages.put(("result", stats))
    except Exception as exc:
        messages.put(("error", str(exc)))
    finally:
        root_logger.removeHandler(handler)


def _parallel_batch_worker(config_kwargs, tasks, options, messages, stop_event):
    """Process assigned file sets serially with one process-local configuration."""
    handler = logging.Handler()
    handler.emit = lambda record: messages.put(("log", (record.levelno, record.getMessage())))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    try:
        processor = BatchProcessor(**config_kwargs)
        for index, file_set, output_directory in tasks:
            if stop_event.is_set():
                break
            processor.set_output_directory(output_directory)
            stats = processor.process_file_set(
                file_set,
                **options,
                progress_callback=lambda current, total, message, index=index: messages.put(
                    ("progress", (index, message))
                ),
                estimate_callback=lambda points: messages.put(("estimate", points)),
                should_continue=lambda: not stop_event.is_set(),
            )
            if stats["failed_indices"] and not stats["cancelled"]:
                retry = processor.process_file_set(
                    file_set, **options, image_indices=stats["failed_indices"],
                    should_continue=lambda: not stop_event.is_set(),
                    progress_callback=lambda current, total, message, index=index: messages.put(
                        ("progress", (index, f"Retry: {message}"))
                    ),
                )
                if retry["failed_indices"]:
                    logger.error(
                        "File set %s could not complete image indices %s after a serial retry",
                        file_set[0], retry["failed_indices"],
                    )
                stats["processed"] += retry["processed"]
                stats["failed"] = retry["failed"]
                stats["failed_indices"] = retry["failed_indices"]
                stats["cancelled"] = stats["cancelled"] or retry["cancelled"]
                for key in ("skipped", "overwritten", "metadata_created", "metadata_updated",
                            "metadata_versioned"):
                    stats[key] += retry[key]
                for key in ("chi_files", "xy_files", "dat_files", "npy_files", "metadata_files"):
                    stats[key].extend(retry[key])
            messages.put(("batch_result", (index, stats)))
            processor._source_metadata_cache.clear()
        messages.put(("batch_done", None))
    except Exception as exc:
        messages.put(("error", str(exc)))
    finally:
        root_logger.removeHandler(handler)


class BatchProcessor:
    """
    Handles batch processing of diffraction images using Dioptas.
    Exports to CHI/XY/DAT files (1D patterns) and NPY files (2D cake images).
    """
    
    def __init__(self, 
                 calibration_file: str,
                 output_directory: str,
                 mask_file: Optional[str] = None,
                 num_points: int = 4857,
                 integration_method: str = 'csr',
                 cake_azimuth_points: int = 360,
                 overwrite: bool = False):
        """
        Initialize batch processor.
        
        Args:
            calibration_file: Path to .poni calibration file
            output_directory: Where to save processed files
            mask_file: Optional path to mask file
            num_points: Number of points in 1D pattern
            integration_method: Integration method ('csr', 'lut', etc.)
            cake_azimuth_points: Number of azimuth bins for cake integration
            overwrite: Whether to overwrite existing files
        """
        self.calibration_file = calibration_file
        self.mask_file = mask_file
        self._mask_available = False
        self._mask_shape_loaded = None
        self.num_points = num_points
        self.integration_method = integration_method
        self.cake_azimuth_points = cake_azimuth_points
        self.overwrite = overwrite
        self._loaded_series_file = None
        self._loaded_series_index = None
        self._source_metadata_cache = {}
        
        self.set_output_directory(output_directory)
        
        # Initialize Dioptas configuration
        self.config = Configuration()
        self._load_calibration()
        self._load_mask()
        
        # Configure integration parameters
        self._apply_integration_settings()
        self.config.auto_integrate_cake = True  # Enable cake integration
        
        logger.info("Batch processor initialized")
        logger.info(f"Calibration: {calibration_file}")
        logger.info("Integration points: automatic (estimated per loaded image)")
        logger.info("CAKE radial points: automatic (matches the estimated 1D points)")

    def set_output_directory(self, output_directory: str | Path):
        """Update the output directory used for subsequent exports."""
        self.output_directory = Path(output_directory).expanduser().resolve()
        existed = self.output_directory.exists()
        self.output_directory.mkdir(parents=True, exist_ok=True)
        if existed:
            logger.info(f"Output: {self.output_directory} (existing directory; incremental update mode)")
        else:
            logger.info(f"Output: {self.output_directory}")

    def _cake_radial_points(self) -> int:
        """CAKE radial bins match the 1D integration point count."""
        return int(self.num_points)

    def _set_config_attrs(self, candidates: List[str], value, label: str) -> List[str]:
        """
        Set value on matching Dioptas attributes across known config sub-models.
        This avoids silently writing unused ad-hoc attributes when names differ
        between Dioptas versions.
        """
        applied = []
        targets = [("config", self.config)]
        calibration_model = getattr(self.config, "calibration_model", None)
        integration_model = getattr(self.config, "integration_model", None)
        if calibration_model is not None:
            targets.append(("calibration_model", calibration_model))
        if integration_model is not None:
            targets.append(("integration_model", integration_model))

        for target_name, target_obj in targets:
            for attr in candidates:
                if hasattr(target_obj, attr):
                    setattr(target_obj, attr, value)
                    applied.append(f"{target_name}.{attr}")

        if not applied:
            logger.warning(
                f"Could not map '{label}' to any known Dioptas config field. "
                f"Tried: {', '.join(candidates)}"
            )
        else:
            logger.info(f"Applied {label}={value} to: {', '.join(applied)}")

        return applied

    def _cake_matches_requested_resolution(self, paths: dict) -> bool:
        """
        Return True when existing cake files match requested GUI resolution.
        """
        try:
            if not (paths["int_path"].exists() and paths["tth_path"].exists() and paths["azi_path"].exists()):
                return False

            tth = np.load(str(paths["tth_path"]), mmap_mode="r")
            azi = np.load(str(paths["azi_path"]), mmap_mode="r")
            intensity = np.load(str(paths["int_path"]), mmap_mode="r")

            tth_len = int(np.asarray(tth).shape[0])
            azi_len = int(np.asarray(azi).shape[0])
            intensity_shape = tuple(np.asarray(intensity).shape)

            expected_cake_rad = self._cake_radial_points()
            if tth_len != expected_cake_rad or azi_len != int(self.cake_azimuth_points):
                logger.info(
                    "Existing cake resolution mismatch; will regenerate "
                    f"(found tth={tth_len}, azi={azi_len}; "
                    f"requested tth={expected_cake_rad}, azi={self.cake_azimuth_points})"
                )
                return False

            if intensity_shape != (azi_len, tth_len):
                logger.info(
                    "Existing cake intensity shape mismatch; will regenerate "
                    f"(found {intensity_shape}, expected {(azi_len, tth_len)})"
                )
                return False

            return True
        except Exception as e:
            logger.warning(f"Failed to validate existing cake resolution: {e}")
            return False

    def _get_existing_cake_dims(self, paths: dict) -> Optional[Tuple[Tuple[int, ...], int, int]]:
        """Return existing cake dimensions as (intensity_shape, tth_len, azi_len)."""
        try:
            if not (paths["int_path"].exists() and paths["tth_path"].exists() and paths["azi_path"].exists()):
                return None
            intensity = np.load(str(paths["int_path"]), mmap_mode="r")
            tth = np.load(str(paths["tth_path"]), mmap_mode="r")
            azi = np.load(str(paths["azi_path"]), mmap_mode="r")
            return (
                tuple(np.asarray(intensity).shape),
                int(np.asarray(tth).shape[0]),
                int(np.asarray(azi).shape[0]),
            )
        except Exception:
            return None

    def _apply_integration_settings(self):
        """Apply radial and azimuth integration settings for both 1D and CAKE."""
        self._set_config_attrs(
            [
                "integration_rad_points",
                "cake_rad_points",
                "cake_tth_points",
                "cake_integration_rad_points",
            ],
            self.num_points,
            "integration points",
        )
        self._set_config_attrs(
            [
                "cake_azimuth_points",
                "cake_azi_points",
                "cake_chi_points",
            ],
            self.cake_azimuth_points,
            "azimuth bins",
        )

    def _load_image_into_config(self, file_set: List[str], image_index: int):
        """Load an image into the Dioptas config for estimation/integration."""
        if len(file_set) == 3:
            lambda_loader = LambdaLoader.LambdaImage(file_list=file_set)
            img_data = lambda_loader.get_image(image_index)
            self.config.img_model.blockSignals(True)
            self.config.img_model.img_data = img_data
            self.config.img_model.blockSignals(False)
            return

        image_model = self.config.img_model
        image_model.blockSignals(True)
        try:
            # Dioptas keeps the frame reader on the image model. Reuse it for
            # sequential snapshots instead of reopening a large HDF5 file.
            if (
                self._loaded_series_file == file_set[0]
                and self._loaded_series_index is not None
                and image_index == self._loaded_series_index + 1
                and callable(getattr(image_model, "load_series_img", None))
                and getattr(image_model, "series_get_image", None) is not None
            ):
                image_model.load_series_img(image_index + 1)
            else:
                image_model.load(file_set[0], image_index)
            self._loaded_series_file = file_set[0]
            self._loaded_series_index = image_index
        except Exception:
            self._loaded_series_file = None
            self._loaded_series_index = None
            raise
        finally:
            image_model.blockSignals(False)

    def estimate_integration_points(self) -> int:
        """
        Ask Dioptas to estimate the recommended 1D radial bin count.
        This mirrors the internal automatic behavior used when num_points=None.
        """
        img_data = getattr(self.config.img_model, "img_data", None)
        if img_data is None:
            return int(self.num_points)

        estimated_points = self.config.calibration_model.calculate_number_of_pattern_points(
            img_data.shape, 2
        )
        return max(1, int(estimated_points))

    def update_integration_points(self, num_points: int):
        """Store and apply a new radial bin count estimate."""
        self.num_points = int(num_points)
        self._apply_integration_settings()
        logger.info(f"Estimated integration points from image: {self.num_points}")
        
    def _load_calibration(self):
        """Load calibration file."""
        if not os.path.exists(self.calibration_file):
            raise FileNotFoundError(f"Calibration file not found: {self.calibration_file}")
            
        try:
            self.config.calibration_model.load(self.calibration_file)
            logger.info("Calibration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")
            raise
            
    def _load_mask(self):
        """Validate mask path and configure mask usage flag."""
        if not self.mask_file:
            self._mask_available = False
            return

        if not os.path.exists(self.mask_file):
            logger.warning(f"Mask file does not exist and will be ignored: {self.mask_file}")
            self._mask_available = False
            return

        # Actual loading is deferred until image dimensions are known.
        self._mask_available = True
        self.config.use_mask = False
        logger.info(f"Mask configured: {self.mask_file}")

    def _ensure_mask_loaded_for_current_image(self):
        """
        Ensure mask is loaded for the current image shape.
        Dioptas mask loading requires the mask model dimension to match image data.
        """
        if not self._mask_available:
            return

        img_data = getattr(self.config.img_model, "img_data", None)
        if img_data is None:
            return

        image_shape = tuple(img_data.shape)
        if self._mask_shape_loaded == image_shape:
            return

        self.config.mask_model.set_dimension(image_shape)
        self.config.mask_model.load_mask(self.mask_file)
        self._mask_shape_loaded = image_shape
        logger.info(f"Mask loaded for image shape {image_shape}: {self.mask_file}")
                
    def group_lambda_files(self, file_list: List[str]) -> List[List[str]]:
        """
        Group Lambda detector files by their base name.
        Multi-module Lambda detectors produce 3 files (m1, m2, m3) per acquisition.
        Single detector image files are treated as individual file sets.
        
        Args:
            file_list: List of file paths
            
        Returns:
            List of file groups, where each group has 3 files (multi-module) or 1 file (single)
        """
        multi_module_groups = {}
        single_files = []
        
        for file_path in file_list:
            if not has_supported_image_extension(file_path):
                logger.info(f"Ignoring non-image input: {file_path}")
                continue
            # Check if this is a multi-module Lambda file (has _m1, _m2, or _m3)
            if re.search(r'_m[1-3](_part\d+)?\.(nxs|h5|hdf|hdf5)$', file_path, re.IGNORECASE):
                # Multi-module Lambda file
                base_name = re.sub(r'_m[1-3](_part\d+)?\.(nxs|h5|hdf|hdf5)$', '', file_path, flags=re.IGNORECASE)
                
                if base_name not in multi_module_groups:
                    multi_module_groups[base_name] = []
                multi_module_groups[base_name].append(file_path)
            else:
                # Single file (no module suffix) - treat as individual file set
                single_files.append([file_path])
        
        # Process multi-module groups - only include complete sets with 3 files
        complete_groups = []
        for base_name, files in multi_module_groups.items():
            if len(files) == 3:
                complete_groups.append(sorted(files))
            else:
                logger.warning(f"Incomplete multi-module file set for {base_name}: {len(files)} files (need 3)")
        
        # Add single files to complete groups
        complete_groups.extend(single_files)
        
        logger.info(f"Grouped into {len(complete_groups)} file set(s): {len([g for g in complete_groups if len(g) == 3])} multi-module, {len(single_files)} single file(s)")
                
        return complete_groups
        
    def get_image_count(self, file_set: List[str]) -> int:
        """
        Get number of images in a file set.
        
        Args:
            file_set: List of 3 Lambda files or one detector image file
            
        Returns:
            Number of images in the dataset
        """
        try:
            if len(file_set) == 3 or has_hdf5_extension(file_set[0]):
                with h5py.File(file_set[0], 'r') as f:
                    data_path = 'entry/instrument/detector/data'
                    if data_path in f:
                        return f[data_path].shape[0]

            try:
                return int(FabioLoader.FabioLoader(file_set[0]).series_max)
            except Exception as fabio_error:
                logger.info(
                    "Could not read frame count with fabIO; treating as one image: "
                    f"{file_set[0]} ({fabio_error})"
                )
                return 1
        except Exception as e:
            logger.error(f"Error reading image count: {e}")
            
        return 0

    def _file_set_base_name(self, file_set: List[str]) -> str:
        """Return the common output base name for a file set."""
        base_name = Path(file_set[0]).stem
        return re.sub(r'_m\d+(_part\d+)?$', '', base_name)

    def _snapshot_output_name(self, base_name: str, image_index: int, n_images: int) -> str:
        """Return a unique output base name for one image in a file set."""
        if n_images > 1:
            snapshot_suffix = f"{image_index + 1:03d}"
            match = re.match(r"^(?P<prefix>.+)_(?P<trailing_index>\d+)$", base_name)
            if match:
                return (
                    f"{match.group('prefix')}_{snapshot_suffix}_"
                    f"{match.group('trailing_index')}"
                )
            return f"{base_name}_{snapshot_suffix}"
        return base_name

    def output_base_names_for_file_set(self, file_set: List[str]) -> List[str]:
        """Return output base names that will be written for a file set."""
        base_name = self._file_set_base_name(file_set)
        n_images = self.get_image_count(file_set)
        if n_images <= 0:
            return [base_name]
        return [
            self._snapshot_output_name(base_name, img_idx, n_images)
            for img_idx in range(n_images)
        ]

    def _build_output_paths(self, base_output_name: str) -> dict:
        """Build output paths for 1D and cake exports for one image."""
        cake_folder = self.output_directory / f"{base_output_name}-param"
        int_path = cake_folder / f"{base_output_name}.int.cake.npy"
        tth_path = cake_folder / f"{base_output_name}.tth.cake.npy"
        azi_path = cake_folder / f"{base_output_name}.azi.cake.npy"

        return {
            "chi_path": self.output_directory / f"{base_output_name}.chi",
            "xy_path": self.output_directory / f"{base_output_name}.xy",
            "dat_path": self.output_directory / f"{base_output_name}.dat",
            "cake_folder": cake_folder,
            "int_path": int_path,
            "tth_path": tth_path,
            "azi_path": azi_path,
            "poni_dest": cake_folder / Path(self.calibration_file).name,
            "metadata_path": cake_folder / f"{base_output_name}{METADATA_FILE_SUFFIX}",
        }

    def _log_overwrite(self, label: str, path: Path):
        """Log an explicit overwrite event for GUI highlighting."""
        logger.info(f"OVERWRITE: {label}: {path.resolve()}")

    def inspect_existing_output(self, base_output_name: str) -> dict:
        """Return an inventory of existing outputs for one output base name."""
        paths = self._build_output_paths(base_output_name)
        cake_folder = paths["cake_folder"]
        metadata_files = sorted(cake_folder.glob("*.metadata*.json")) if cake_folder.exists() else []
        version_markers = []
        if cake_folder.exists():
            for pattern in ("*version*", "*.version", "*.schema*"):
                version_markers.extend(cake_folder.glob(pattern))

        return {
            "output_directory": self.output_directory,
            "param_folder": cake_folder,
            "param_folder_exists": cake_folder.exists(),
            "metadata_path": paths["metadata_path"],
            "metadata_exists": paths["metadata_path"].exists(),
            "metadata_files": metadata_files,
            "version_markers": sorted(set(version_markers)),
            "processing_artifacts": {
                "chi": paths["chi_path"].exists(),
                "xy": paths["xy_path"].exists(),
                "dat": paths["dat_path"].exists(),
                "cake_intensity": paths["int_path"].exists(),
                "cake_two_theta": paths["tth_path"].exists(),
                "cake_azimuth": paths["azi_path"].exists(),
                "poni": paths["poni_dest"].exists(),
            },
        }

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        """Convert common HDF5/numpy values to JSON-compatible values."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            if value.shape == ():
                return BatchProcessor._json_safe_value(value.item())
            return [BatchProcessor._json_safe_value(item) for item in value.tolist()]
        if isinstance(value, (list, tuple)):
            return [BatchProcessor._json_safe_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): BatchProcessor._json_safe_value(item) for key, item in value.items()}
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @classmethod
    def _attrs_to_dict(cls, attrs) -> dict:
        """Return HDF5 attributes as a JSON-compatible dictionary."""
        result = {}
        for key in attrs.keys():
            try:
                result[str(key)] = cls._json_safe_value(attrs[key])
            except Exception as exc:
                result[str(key)] = {"error": f"Could not serialize attribute: {exc}"}
        return result

    @staticmethod
    def _dataset_size(dataset) -> int:
        """Return total dataset item count, treating scalar datasets as one item."""
        shape = tuple(dataset.shape)
        if not shape:
            return 1
        return int(np.prod(shape))

    @classmethod
    def _dataset_value_summary(cls, path: str, dataset) -> dict:
        """Return JSON-safe dataset metadata, inlining only modest-size values."""
        item_count = cls._dataset_size(dataset)
        summary = {
            "dtype": str(dataset.dtype),
            "shape": list(dataset.shape),
            "ndim": int(dataset.ndim),
            "size": item_count,
        }
        if item_count <= MAX_INLINE_DATASET_ITEMS:
            try:
                summary["value"] = cls._json_safe_value(dataset[()])
            except Exception as exc:
                summary["value_error"] = str(exc)
        else:
            summary["value_omitted"] = (
                "dataset is too large for inline metadata export; "
                f"limit={MAX_INLINE_DATASET_ITEMS}"
            )
        if path.lower().endswith("/data") and dataset.ndim >= 2:
            summary["role_hint"] = "detector_data"
        return summary

    @classmethod
    def _hdf5_node_to_dict(cls, name: str, obj) -> dict:
        """Serialize one HDF5 object without discarding unknown metadata fields."""
        path = "/" if name == "" else f"/{name}"
        attrs = cls._attrs_to_dict(obj.attrs)
        node = {
            "path": path,
            "name": Path(path).name if path != "/" else "/",
            "attrs": attrs,
        }
        nx_class = attrs.get("NX_class")
        if nx_class is not None:
            node["NX_class"] = nx_class

        if isinstance(obj, h5py.Dataset):
            node["type"] = "dataset"
            node["dataset"] = cls._dataset_value_summary(path, obj)
        elif isinstance(obj, h5py.Group):
            node["type"] = "group"
        else:
            node["type"] = type(obj).__name__
        return node

    @classmethod
    def _canonical_metadata_fields(cls, nodes: dict) -> dict:
        """
        Build a small alias index for common downstream consumers.
        The full HDF5 tree remains the authoritative generic structure.
        """
        canonical = {}
        for path, node in nodes.items():
            lower_path = path.lower()
            if node.get("type") != "dataset":
                continue
            value = node.get("dataset", {}).get("value")
            if value is None:
                continue
            name = path.rsplit("/", 1)[-1].lower()
            if name in {"x", "x_position", "sample_x", "map_x"}:
                canonical.setdefault("coordinates", {}).setdefault("x", []).append(
                    {"path": path, "value": value}
                )
            elif name in {"y", "y_position", "sample_y", "map_y"}:
                canonical.setdefault("coordinates", {}).setdefault("y", []).append(
                    {"path": path, "value": value}
                )
            elif "detector" in lower_path:
                canonical.setdefault("detector", []).append(path)
            elif "instrument" in lower_path:
                canonical.setdefault("instrument", []).append(path)
            elif "scan" in lower_path:
                canonical.setdefault("scan", []).append(path)
            elif "snapshot" in lower_path:
                canonical.setdefault("snapshots", []).append(path)
        return canonical

    @classmethod
    def _export_hdf5_file_metadata(cls, file_path: str | Path) -> dict:
        """Recursively export HDF5 metadata and modest-size datasets from one file."""
        path = Path(file_path).expanduser().resolve()
        stat = path.stat()
        with h5py.File(path, "r") as h5_file:
            nodes = {"/": cls._hdf5_node_to_dict("", h5_file)}

            def visitor(name, obj):
                nodes[f"/{name}"] = cls._hdf5_node_to_dict(name, obj)

            h5_file.visititems(visitor)

        return {
            "path": str(path),
            "name": path.name,
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "hdf5": {
                "nodes": nodes,
                "canonical": cls._canonical_metadata_fields(nodes),
            },
        }

    @classmethod
    def _export_generic_file_metadata(cls, file_path: str | Path) -> dict:
        """Export durable file metadata for non-HDF5 diffraction images."""
        path = Path(file_path).expanduser().resolve()
        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "format": {
                "extension": path.suffix.lower(),
                "metadata_detail": "generic_file",
            },
        }

    @classmethod
    def _export_source_file_metadata(cls, file_path: str | Path) -> dict:
        """Export HDF5 metadata when available, otherwise generic file metadata."""
        if has_hdf5_extension(file_path):
            return cls._export_hdf5_file_metadata(file_path)
        return cls._export_generic_file_metadata(file_path)

    @classmethod
    def build_metadata_export(
        cls,
        file_set: List[str],
        image_index: int,
        base_output_name: str,
        source_files: Optional[List[dict]] = None,
    ) -> dict:
        """Build the schema-versioned metadata document for one processed image."""
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "generator": "dioptas_batch_gui",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "output_base_name": base_output_name,
            "image_index": int(image_index),
            "source_files": source_files if source_files is not None else [
                cls._export_source_file_metadata(file_path) for file_path in file_set
            ],
            "provenance": {
                "source_file_count": len(file_set),
                "metadata_export": "recursive_hdf5_or_generic_file",
                "large_dataset_inline_item_limit": MAX_INLINE_DATASET_ITEMS,
            },
        }

    @staticmethod
    def _deep_fill_missing(existing: dict, incoming: dict) -> bool:
        """Fill keys missing from existing with incoming values; return True if changed."""
        changed = False
        for key, value in incoming.items():
            if key not in existing:
                existing[key] = value
                changed = True
            elif isinstance(existing[key], dict) and isinstance(value, dict):
                changed = BatchProcessor._deep_fill_missing(existing[key], value) or changed
        return changed

    @staticmethod
    def _write_json_atomic(path: Path, data: dict):
        """Write JSON atomically to avoid leaving a partial metadata file."""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(path)

    @staticmethod
    def _temporary_output_path(path: Path) -> Path:
        """Use a unique sibling path while retaining the export format suffix."""
        return path.with_name(f".{path.stem}.{uuid.uuid4().hex}{path.suffix}")

    def _save_pattern_atomic(self, path: Path):
        temporary = self._temporary_output_path(path)
        try:
            self.config.save_pattern(str(temporary))
            # Dioptas writes the output filename into some pattern headers.
            # Keep that header pointing at the published filename.
            content = temporary.read_bytes()
            header, separator, body = content.partition(b"\n")
            header = header.replace(temporary.name.encode(), path.name.encode())
            temporary.write_bytes(header + separator + body)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _save_npy_atomic(cls, path: Path, array):
        temporary = cls._temporary_output_path(path)
        try:
            np.save(str(temporary), array)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _copy_file_atomic(cls, source: str | Path, destination: Path):
        temporary = cls._temporary_output_path(destination)
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def export_metadata_for_image(
        self,
        file_set: List[str],
        image_index: int,
        base_output_name: str,
    ) -> tuple[Path, str]:
        """
        Create or safely extend the HDF5 metadata export for one image.

        Returns:
            Tuple of written-or-existing path and action: created, updated, unchanged,
            overwritten, or versioned.
        """
        paths = self._build_output_paths(base_output_name)
        metadata_path = paths["metadata_path"]
        paths["cake_folder"].mkdir(parents=True, exist_ok=True)
        source_files = []
        for file_path in file_set:
            source_path = Path(file_path).expanduser().resolve()
            stat = source_path.stat()
            key = (str(source_path), stat.st_size, stat.st_mtime_ns)
            if key not in self._source_metadata_cache:
                self._source_metadata_cache[key] = self._export_source_file_metadata(source_path)
                # Keep only a few sources in memory during watch mode.
                while len(self._source_metadata_cache) > 4:
                    self._source_metadata_cache.pop(next(iter(self._source_metadata_cache)))
            source_files.append(self._source_metadata_cache[key])
        metadata = self.build_metadata_export(
            file_set, image_index, base_output_name, source_files=source_files
        )

        if not metadata_path.exists():
            self._write_json_atomic(metadata_path, metadata)
            logger.info(f"Saved metadata file: {metadata_path.resolve()}")
            return metadata_path, "created"

        if self.overwrite:
            self._log_overwrite("metadata file", metadata_path)
            self._write_json_atomic(metadata_path, metadata)
            logger.info(f"Saved metadata file: {metadata_path.resolve()}")
            return metadata_path, "overwritten"

        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                existing = json.load(handle)
        except Exception as exc:
            versioned_path = metadata_path.with_name(
                f"{metadata_path.stem}.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                f"{metadata_path.suffix}"
            )
            self._write_json_atomic(versioned_path, metadata)
            logger.warning(
                "Existing metadata file could not be read safely; wrote versioned metadata "
                f"file instead: {versioned_path.resolve()} ({exc})"
            )
            return versioned_path, "versioned"

        if not isinstance(existing, dict) or existing.get("schema_version") != METADATA_SCHEMA_VERSION:
            versioned_path = metadata_path.with_name(
                f"{metadata_path.stem}.schema-{METADATA_SCHEMA_VERSION}."
                f"{datetime.now().strftime('%Y%m%d%H%M%S')}{metadata_path.suffix}"
            )
            self._write_json_atomic(versioned_path, metadata)
            logger.warning(
                "Existing metadata schema is incompatible or unknown; wrote versioned metadata "
                f"file instead: {versioned_path.resolve()}"
            )
            return versioned_path, "versioned"

        if self._deep_fill_missing(existing, metadata):
            self._write_json_atomic(metadata_path, existing)
            logger.info(f"Updated metadata file with missing sections: {metadata_path.resolve()}")
            return metadata_path, "updated"

        logger.info(f"Skipping existing metadata file: {metadata_path.resolve()}")
        return metadata_path, "unchanged"
        
    def process_lambda_image(self, 
                            file_set: List[str], 
                            image_index: int,
                            base_output_name: str,
                            export_chi: bool = True,
                            export_xy: bool = False,
                            export_dat: bool = False,
                            export_cake_npy: bool = True,
                            apply_mask_to_chi: bool = True,
                            apply_mask_to_cake: bool = False,
                            export_metadata: bool = True,
                            estimate_callback: Optional[Callable[[int], None]] = None) -> dict:
        """
        Process a single detector image.
        Handles both multi-module Lambda files and single HDF5 files.
        
        Args:
            file_set: List of files (3 for Lambda, 1 for single file)
            image_index: Index of image to process
            base_output_name: Base name for output files
            export_chi: Export 1D pattern as CHI file
            export_xy: Export 1D pattern as XY file
            export_dat: Export 1D pattern as DAT file
            export_cake_npy: Export 2D cake as NPY file
            export_metadata: Export source HDF5 metadata as JSON
            apply_mask_to_chi: Apply mask during CHI integration
            apply_mask_to_cake: Apply mask during cake integration
            
        Returns:
            Dictionary with processing results
        """
        results = {
            'success': False,
            'chi_file': None,
            'xy_file': None,
            'dat_file': None,
            'npy_file': None,
            'npy_files': None,
            'metadata_file': None,
            'metadata_action': None,
            'skipped': False,
            'overwritten': False,
        }
        paths = self._build_output_paths(base_output_name)
        inventory = self.inspect_existing_output(base_output_name)
        logger.info(
            "Existing output inventory for "
            f"{base_output_name}: param_folder={inventory['param_folder_exists']}, "
            f"metadata={inventory['metadata_exists']}, "
            f"artifacts={inventory['processing_artifacts']}"
        )
        chi_exists = paths["chi_path"].exists()
        xy_exists = paths["xy_path"].exists()
        dat_exists = paths["dat_path"].exists()
        cake_int_exists = paths["int_path"].exists()
        cake_tth_exists = paths["tth_path"].exists()
        cake_azi_exists = paths["azi_path"].exists()
        cake_files_exist = cake_int_exists and cake_tth_exists and cake_azi_exists
        
        try:
            if not any([export_chi, export_xy, export_dat, export_cake_npy, export_metadata]):
                raise ValueError("No outputs selected for export")

            image_loaded = False

            def load_image_and_estimate_points():
                nonlocal image_loaded
                if image_loaded:
                    return
                self._load_image_into_config(file_set, image_index)
                estimated_points = self.estimate_integration_points()
                self.update_integration_points(estimated_points)
                if estimate_callback:
                    estimate_callback(estimated_points)
                image_loaded = True

            # Respect "overwrite existing files" before doing any image-loading or integration work.
            if not self.overwrite:
                chi_ready = (not export_chi) or chi_exists
                xy_ready = (not export_xy) or xy_exists
                dat_ready = (not export_dat) or dat_exists
                cake_ready = not export_cake_npy
                if export_cake_npy and cake_files_exist:
                    load_image_and_estimate_points()
                    cake_ready = self._cake_matches_requested_resolution(paths)
                metadata_ready = (not export_metadata) or paths["metadata_path"].exists()

                if chi_ready and xy_ready and dat_ready and cake_ready and metadata_ready:
                    existing_dims = self._get_existing_cake_dims(paths) if export_cake_npy else None
                    metadata_action = None
                    if export_metadata:
                        metadata_path, metadata_action = self.export_metadata_for_image(
                            file_set, image_index, base_output_name
                        )
                        results['metadata_file'] = str(metadata_path)
                        results['metadata_action'] = metadata_action
                    if export_chi:
                        results['chi_file'] = str(paths["chi_path"])
                    if export_xy:
                        results['xy_file'] = str(paths["xy_path"])
                    if export_dat:
                        results['dat_file'] = str(paths["dat_path"])
                    if export_cake_npy:
                        results['npy_files'] = [
                            str(paths["int_path"]),
                            str(paths["tth_path"]),
                            str(paths["azi_path"]),
                        ]
                        results['npy_file'] = str(paths["int_path"])
                        paths["cake_folder"].mkdir(parents=True, exist_ok=True)
                        if not paths["poni_dest"].exists():
                            try:
                                self._copy_file_atomic(self.calibration_file, paths["poni_dest"])
                                logger.debug(f"Copied poni file to {paths['cake_folder']}")
                            except Exception as e:
                                logger.warning(f"Failed to copy poni file: {e}")

                    logger.info(
                        f"SKIPPED: image {image_index}: outputs already exist for {base_output_name}"
                    )
                    if metadata_action in {"created", "updated", "versioned"}:
                        logger.info(
                            "Incremental metadata update completed for "
                            f"{base_output_name}: {metadata_action}"
                        )
                    if existing_dims is not None:
                        logger.info(
                            "Using existing CAKE files with bins: "
                            f"intensity_shape={existing_dims[0]}, tth={existing_dims[1]}, azi={existing_dims[2]}"
                        )
                    results['success'] = True
                    results['skipped'] = True
                    return results

            load_image_and_estimate_points()

            cake_ready = cake_files_exist and self._cake_matches_requested_resolution(paths)
            if export_cake_npy and cake_files_exist and not self.overwrite and not cake_ready:
                raise RuntimeError(
                    "Existing CAKE files do not match the requested resolution. "
                    "Enable overwrite to regenerate them."
                )
            need_chi_processing = export_chi and (self.overwrite or not chi_exists)
            need_xy_processing = export_xy and (self.overwrite or not xy_exists)
            need_dat_processing = export_dat and (self.overwrite or not dat_exists)
            need_cake_processing = export_cake_npy and (
                self.overwrite or not cake_ready
            )
            need_1d_processing = need_chi_processing or need_xy_processing or need_dat_processing

            if self._mask_available and (
                (need_1d_processing and apply_mask_to_chi)
                or (need_cake_processing and apply_mask_to_cake)
            ):
                self._ensure_mask_loaded_for_current_image()

            # Re-apply settings in case Dioptas resets them on image load.
            if need_1d_processing or need_cake_processing:
                self._apply_integration_settings()
            
            # Integrate 1D with optional mask
            if need_1d_processing:
                self.config.use_mask = bool(self._mask_available and apply_mask_to_chi)
                self.config.integrate_image_1d()

            # Integrate 2D cake with optional mask
            if need_cake_processing:
                self.config.use_mask = bool(self._mask_available and apply_mask_to_cake)
                if self.config.use_mask:
                    cake_mask = self.config.mask_model.get_mask()
                elif self.config.mask_model.roi is not None:
                    cake_mask = self.config.mask_model.roi_mask
                else:
                    cake_mask = None

                # Call calibration_model directly so CAKE resolution is forced from GUI values.
                logger.info(
                    "Integrating CAKE with requested bins: "
                    f"radial={self._cake_radial_points()}, azimuth={self.cake_azimuth_points}"
                )
                self.config.calibration_model.integrate_2d(
                    mask=cake_mask,
                    rad_points=self._cake_radial_points(),
                    azimuth_points=int(self.cake_azimuth_points),
                    azimuth_range=self.config.cake_azimuth_range,
                )
            
            # Export 1D pattern files
            if export_chi:
                chi_path = paths["chi_path"]
                
                if not need_chi_processing:
                    logger.info(f"Skipping existing CHI file: {chi_path.resolve()}")
                    results['chi_file'] = str(chi_path)
                    results['skipped'] = True
                else:
                    if self.overwrite and chi_exists:
                        results['overwritten'] = True
                        self._log_overwrite("CHI file", chi_path)
                    self._save_pattern_atomic(chi_path)
                    results['chi_file'] = str(chi_path)
                    logger.info(f"Saved CHI file: {chi_path.resolve()}")

            if export_xy:
                xy_path = paths["xy_path"]

                if not need_xy_processing:
                    logger.info(f"Skipping existing XY file: {xy_path.resolve()}")
                    results['xy_file'] = str(xy_path)
                    results['skipped'] = True
                else:
                    if self.overwrite and xy_exists:
                        results['overwritten'] = True
                        self._log_overwrite("XY file", xy_path)
                    self._save_pattern_atomic(xy_path)
                    results['xy_file'] = str(xy_path)
                    logger.info(f"Saved XY file: {xy_path.resolve()}")

            if export_dat:
                dat_path = paths["dat_path"]

                if not need_dat_processing:
                    logger.info(f"Skipping existing DAT file: {dat_path.resolve()}")
                    results['dat_file'] = str(dat_path)
                    results['skipped'] = True
                else:
                    if self.overwrite and dat_exists:
                        results['overwritten'] = True
                        self._log_overwrite("DAT file", dat_path)
                    self._save_pattern_atomic(dat_path)
                    results['dat_file'] = str(dat_path)
                    logger.info(f"Saved DAT file: {dat_path.resolve()}")
                
            # Export cake as separate NPY files (intensity, azimuth/chi, two-theta)
            # Save in a subfolder: filename-param/
            if export_cake_npy:
                # Create subfolder for cake files: filename-param
                cake_folder = paths["cake_folder"]
                cake_folder.mkdir(parents=True, exist_ok=True)
                
                # Copy poni file to param folder
                poni_dest = paths["poni_dest"]
                if not poni_dest.exists() or self.overwrite:
                    try:
                        if self.overwrite and poni_dest.exists():
                            results['overwritten'] = True
                            self._log_overwrite("PONI file", poni_dest)
                        self._copy_file_atomic(self.calibration_file, poni_dest)
                        logger.debug(f"Copied poni file to {cake_folder}")
                    except Exception as e:
                        logger.warning(f"Failed to copy poni file: {e}")
                
                int_path = paths["int_path"]
                tth_path = paths["tth_path"]
                azi_path = paths["azi_path"]

                if not need_cake_processing:
                    logger.info(
                        "Skipping existing cake files: "
                        f"{int_path.resolve()}, {tth_path.resolve()}, {azi_path.resolve()}"
                    )
                    results['npy_files'] = [str(int_path), str(tth_path), str(azi_path)]
                    results['npy_file'] = str(int_path)
                    results['skipped'] = True
                else:
                    # Get cake data from Dioptas
                    # cake_img = 2D intensity array (azimuth x radial)
                    # cake_tth = 1D array of 2-theta values (radial axis)
                    # cake_azi = 1D array of azimuthal/chi values (azimuth axis)
                    intensity_cake = self.config.calibration_model.cake_img
                    tth_cake = self.config.calibration_model.cake_tth
                    chi_cake = self.config.calibration_model.cake_azi

                    expected_cake_rad = self._cake_radial_points()
                    expected_shape = (int(self.cake_azimuth_points), expected_cake_rad)
                    actual_shape = tuple(np.asarray(intensity_cake).shape)
                    actual_tth_len = int(np.asarray(tth_cake).shape[0])
                    actual_azi_len = int(np.asarray(chi_cake).shape[0])
                    if (
                        actual_shape != expected_shape
                        or actual_tth_len != expected_cake_rad
                        or actual_azi_len != int(self.cake_azimuth_points)
                    ):
                        raise RuntimeError(
                            "CAKE resolution mismatch after integration: "
                            f"expected int={expected_shape}, tth={expected_cake_rad}, azi={self.cake_azimuth_points}; "
                            f"got int={actual_shape}, tth={actual_tth_len}, azi={actual_azi_len}"
                        )
                    logger.info(
                        "CAKE integrated with actual bins: "
                        f"intensity_shape={actual_shape}, tth={actual_tth_len}, azi={actual_azi_len}"
                    )

                    if self.overwrite and cake_int_exists:
                        results['overwritten'] = True
                        self._log_overwrite("CAKE intensity file", int_path)
                    if self.overwrite or not cake_int_exists:
                        self._save_npy_atomic(int_path, intensity_cake)
                    if self.overwrite and cake_tth_exists:
                        results['overwritten'] = True
                        self._log_overwrite("CAKE two-theta file", tth_path)
                    if self.overwrite or not cake_tth_exists:
                        self._save_npy_atomic(tth_path, tth_cake)
                    if self.overwrite and cake_azi_exists:
                        results['overwritten'] = True
                        self._log_overwrite("CAKE azimuth file", azi_path)
                    if self.overwrite or not cake_azi_exists:
                        self._save_npy_atomic(azi_path, chi_cake)
                    results['npy_files'] = [str(int_path), str(tth_path), str(azi_path)]
                    results['npy_file'] = str(int_path)
                    logger.info(
                        "Saved cake files: "
                        f"{int_path.resolve()}, {tth_path.resolve()}, {azi_path.resolve()}"
                    )

            if export_metadata:
                metadata_path, metadata_action = self.export_metadata_for_image(
                    file_set, image_index, base_output_name
                )
                results['metadata_file'] = str(metadata_path)
                results['metadata_action'] = metadata_action
                if metadata_action == "overwritten":
                    results['overwritten'] = True
                
            results['success'] = True
            
        except Exception as e:
            logger.error(f"Error processing image {image_index}: {e}")
            results['error'] = str(e)
            
        return results
        
    def _process_file_set_parallel(
        self, file_set, n_images, options, progress_callback, estimate_callback,
        should_continue, worker_count,
    ) -> dict:
        """Process non-overlapping frame ranges in independent processes."""
        context = multiprocessing.get_context("spawn")
        messages = context.Queue()
        stop_event = context.Event()
        ranges = [
            list(range(n_images * worker // worker_count,
                       n_images * (worker + 1) // worker_count))
            for worker in range(worker_count)
        ]
        config_kwargs = {
            "calibration_file": self.calibration_file,
            "output_directory": str(self.output_directory),
            "mask_file": self.mask_file,
            "num_points": self.num_points,
            "integration_method": self.integration_method,
            "cake_azimuth_points": self.cake_azimuth_points,
            "overwrite": self.overwrite,
        }
        processes = [
            context.Process(
                target=_parallel_file_worker,
                args=(config_kwargs, file_set, indices, options, messages, stop_event),
            )
            for indices in ranges
        ]
        worker_stats = []
        completed = 0
        launched_processes = []
        abort_deadline = None
        aborted_early = False
        try:
            for process in processes:
                process.start()
                launched_processes.append(process)
            while len(worker_stats) < len(processes):
                if should_continue is not None and not should_continue():
                    stop_event.set()
                    if abort_deadline is None:
                        abort_deadline = time.monotonic() + ABORT_WORKER_GRACE_SECONDS
                if abort_deadline is not None and time.monotonic() >= abort_deadline:
                    aborted_early = True
                    break
                try:
                    kind, payload = messages.get(timeout=0.2)
                except queue.Empty:
                    if all(not process.is_alive() for process in processes):
                        if abort_deadline is not None:
                            aborted_early = True
                            break
                        # A child may have exited without delivering its result.
                        raise RuntimeError("Parallel worker exited without a result")
                    continue
                if kind == "log":
                    logger.log(*payload)
                elif kind == "progress":
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, n_images, payload)
                elif kind == "estimate" and estimate_callback:
                    estimate_callback(payload)
                elif kind == "result":
                    worker_stats.append(payload)
                elif kind == "error":
                    stop_event.set()
                    raise RuntimeError(f"Parallel worker failed: {payload}")
        finally:
            stop_event.set()
            for process in launched_processes:
                process.join(timeout=0.2 if abort_deadline is not None else 10)
                if process.is_alive():
                    process.terminate()
                    process.join()
            messages.close()
            messages.join_thread()

        if aborted_early:
            stats = _empty_file_stats(n_images)
            stats["processed"] = completed
            stats["cancelled"] = True
            return stats

        merged = worker_stats[0]
        for part in worker_stats[1:]:
            for key in (
                "processed", "failed", "skipped", "overwritten", "metadata_created",
                "metadata_updated", "metadata_versioned",
            ):
                merged[key] += part[key]
            for key in ("chi_files", "xy_files", "dat_files", "npy_files", "metadata_files"):
                merged[key].extend(part[key])
            merged["failed_indices"].extend(part["failed_indices"])
            merged["cancelled"] = merged["cancelled"] or part["cancelled"]
        if should_continue is not None and not should_continue():
            merged["cancelled"] = True
        if merged["failed_indices"] and should_continue is not None and not should_continue():
            merged["cancelled"] = True
        if merged["failed_indices"] and not merged["cancelled"]:
            failed_indices = sorted(merged["failed_indices"])
            logger.warning(
                "Retrying %d failed image(s) in the main process: %s",
                len(failed_indices), failed_indices,
            )
            retry_completed = 0

            def report_retry(current, total, message):
                nonlocal retry_completed
                retry_completed += 1
                if progress_callback:
                    progress_callback(completed + retry_completed, n_images, f"Retry: {message}")

            retry = self.process_file_set(
                file_set,
                **options,
                image_indices=failed_indices,
                estimate_callback=estimate_callback,
                should_continue=should_continue,
                progress_callback=report_retry if progress_callback else None,
            )
            merged["failed"] -= len(failed_indices)
            for key in (
                "processed", "failed", "skipped", "overwritten", "metadata_created",
                "metadata_updated", "metadata_versioned",
            ):
                merged[key] += retry[key]
            for key in ("chi_files", "xy_files", "dat_files", "npy_files", "metadata_files"):
                merged[key].extend(retry[key])
            merged["failed_indices"] = retry["failed_indices"]
            merged["cancelled"] = retry["cancelled"]
            if retry["cancelled"]:
                merged["failed"] += len(failed_indices) - retry["processed"] - retry["failed"]
            elif merged["failed_indices"]:
                raise RuntimeError(
                    "Parallel processing could not complete image indices "
                    f"{merged['failed_indices']} after a serial retry"
                )
        merged["total_images"] = n_images
        for key in ("chi_files", "xy_files", "dat_files", "npy_files", "metadata_files"):
            merged[key].sort()
        return merged

    def process_file_sets(
        self, file_sets, output_directories, workers=1, progress_callback=None,
        estimate_callback=None, should_continue=None, **options,
    ) -> dict:
        """Process Batch mode file sets within one global worker budget."""
        if len(file_sets) != len(output_directories):
            raise ValueError("Each file set needs an output directory")
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if not file_sets:
            return {"file_results": [], "total_images": 0, "processed": 0, "cancelled": False}

        counts = [self.get_image_count(file_set) for file_set in file_sets]
        total_images = sum(counts)
        results = [None] * len(file_sets)
        completed = 0

        def report_progress(index, message):
            nonlocal completed
            completed += 1
            if progress_callback:
                progress_callback(
                    completed, total_images,
                    f"{Path(file_sets[index][0]).name}: {message}",
                )

        if len(file_sets) == 1:
            self.set_output_directory(output_directories[0])
            results[0] = self.process_file_set(
                file_sets[0], workers=workers,
                progress_callback=lambda current, total, message: report_progress(0, message),
                estimate_callback=estimate_callback, should_continue=should_continue, **options,
            )
        else:
            # Files with the same output stem must stay on one worker to avoid
            # writing the same artifact at the same time.
            grouped = {}
            output_names = set()
            output_collision = False
            for index, (file_set, output_directory) in enumerate(zip(file_sets, output_directories)):
                directory = str(Path(output_directory).resolve())
                key = (directory, self._file_set_base_name(file_set))
                grouped.setdefault(key, []).append(index)
                base = self._file_set_base_name(file_set)
                for image_index in range(counts[index]):
                    base_name = self._snapshot_output_name(base, image_index, counts[index])
                    output_key = (directory, base_name)
                    if output_key in output_names:
                        output_collision = True
                    output_names.add(output_key)
            groups = sorted(grouped.values(), key=lambda group: -sum(counts[i] for i in group))
            worker_count = min(workers, len(groups), conservative_worker_limit())
            if output_collision:
                logger.warning("Overlapping output names detected; processing this batch serially")
                worker_count = 1
            if worker_count == 1:
                for index, (file_set, output_directory) in enumerate(zip(file_sets, output_directories)):
                    if should_continue is not None and not should_continue():
                        break
                    self.set_output_directory(output_directory)
                    results[index] = self.process_file_set(
                        file_set,
                        progress_callback=lambda current, total, message, index=index:
                            report_progress(index, message),
                        estimate_callback=estimate_callback, should_continue=should_continue,
                        **options,
                    )
                    self._source_metadata_cache.clear()
            else:
                assignments = [[] for _ in range(worker_count)]
                loads = [0] * worker_count
                for group in groups:
                    worker = min(range(worker_count), key=lambda i: loads[i])
                    for index in group:
                        assignments[worker].append((index, file_sets[index], output_directories[index]))
                        loads[worker] += counts[index]
                context = multiprocessing.get_context("spawn")
                messages = context.Queue()
                stop_event = context.Event()
                config_kwargs = {
                    "calibration_file": self.calibration_file,
                    "output_directory": str(output_directories[0]),
                    "mask_file": self.mask_file,
                    "num_points": self.num_points,
                    "integration_method": self.integration_method,
                    "cake_azimuth_points": self.cake_azimuth_points,
                    "overwrite": self.overwrite,
                }
                processes = [
                    context.Process(
                        target=_parallel_batch_worker,
                        args=(config_kwargs, tasks, options, messages, stop_event),
                    )
                    for tasks in assignments
                ]
                launched = []
                done = 0
                abort_deadline = None
                try:
                    for process in processes:
                        process.start()
                        launched.append(process)
                    while done < len(processes):
                        if should_continue is not None and not should_continue():
                            stop_event.set()
                            if abort_deadline is None:
                                abort_deadline = time.monotonic() + ABORT_WORKER_GRACE_SECONDS
                        if abort_deadline is not None and time.monotonic() >= abort_deadline:
                            break
                        try:
                            kind, payload = messages.get(timeout=0.2)
                        except queue.Empty:
                            if all(not process.is_alive() for process in processes):
                                if abort_deadline is not None:
                                    break
                                raise RuntimeError("Batch worker exited without a result")
                            continue
                        if kind == "log":
                            logger.log(*payload)
                        elif kind == "progress":
                            report_progress(*payload)
                        elif kind == "estimate" and estimate_callback:
                            estimate_callback(payload)
                        elif kind == "batch_result":
                            index, stats = payload
                            results[index] = stats
                        elif kind == "batch_done":
                            done += 1
                        elif kind == "error":
                            stop_event.set()
                            raise RuntimeError(f"Batch worker failed: {payload}")
                finally:
                    stop_event.set()
                    for process in launched:
                        process.join(timeout=0.2 if abort_deadline is not None else 10)
                        if process.is_alive():
                            process.terminate()
                            process.join()
                    messages.close()
                    messages.join_thread()

        return {
            "file_results": list(zip(file_sets, results)),
            "total_images": total_images,
            "processed": max(
                completed, sum(stats["processed"] for stats in results if stats is not None)
            ),
            "cancelled": (
                any(stats is None or stats["cancelled"] for stats in results)
                or (should_continue is not None and not should_continue())
            ),
        }

    def process_file_set(self, 
                        file_set: List[str],
                        export_chi: bool = True,
                        export_xy: bool = False,
                        export_dat: bool = False,
                        export_cake_npy: bool = True,
                        apply_mask_to_chi: bool = True,
                        apply_mask_to_cake: bool = False,
                        export_metadata: bool = True,
                        progress_callback=None,
                        estimate_callback: Optional[Callable[[int], None]] = None,
                        should_continue: Optional[Callable[[], bool]] = None,
                        workers: int = 1,
                        image_indices: Optional[List[int]] = None) -> dict:
        """
        Process all images in a file set.
        
        Args:
            file_set: List of 3 Lambda files or one detector image file
            export_chi: Export 1D patterns as CHI files
            export_xy: Export 1D patterns as XY files
            export_dat: Export 1D patterns as DAT files
            export_cake_npy: Export 2D cakes as NPY files
            export_metadata: Export source metadata as JSON
            apply_mask_to_chi: Apply mask during CHI integration
            apply_mask_to_cake: Apply mask during cake integration
            progress_callback: Optional callback function(current, total, status_msg)
            workers: Requested process count for a multi-frame file (1 is serial)
            image_indices: Optional subset used by independent worker processes
            
        Returns:
            Dictionary with processing statistics
        """
        if not file_set or any(not has_supported_image_extension(path) for path in file_set):
            raise ValueError("File set must contain supported diffraction image files")

        stats = _empty_file_stats()
        
        # Get base name for output files
        base_name = self._file_set_base_name(file_set)
        
        # Get number of images
        n_images = self.get_image_count(file_set)
        stats['total_images'] = n_images
        
        if n_images == 0:
            logger.error(f"No images found in file set")
            return stats

        if workers < 1:
            raise ValueError("workers must be at least 1")
        worker_count = min(workers, n_images, conservative_worker_limit())
        if worker_count > 1 and image_indices is None and len(file_set) == 1:
            if worker_count < workers:
                logger.info("Limited worker count from %d to %d", workers, worker_count)
            logger.info("Processing %d images with %d worker processes", n_images, worker_count)
            return self._process_file_set_parallel(
                file_set, n_images,
                {
                    "export_chi": export_chi,
                    "export_xy": export_xy,
                    "export_dat": export_dat,
                    "export_cake_npy": export_cake_npy,
                    "apply_mask_to_chi": apply_mask_to_chi,
                    "apply_mask_to_cake": apply_mask_to_cake,
                    "export_metadata": export_metadata,
                },
                progress_callback, estimate_callback, should_continue, worker_count,
            )

        indices = range(n_images) if image_indices is None else image_indices
        stats['total_images'] = len(indices)
            
        logger.info(f"Processing {n_images} images from {base_name}")
        
        # Process each image
        for img_idx in indices:
            if should_continue is not None and not should_continue():
                stats['cancelled'] = True
                logger.info(
                    f"Processing cancelled before image {img_idx + 1}/{n_images} from {base_name}"
                )
                break

            results = self.process_lambda_image(
                file_set,
                img_idx,
                self._snapshot_output_name(base_name, img_idx, n_images),
                export_chi,
                export_xy,
                export_dat,
                export_cake_npy,
                apply_mask_to_chi,
                apply_mask_to_cake,
                export_metadata,
                estimate_callback=estimate_callback,
            )
            
            if results['success']:
                stats['processed'] += 1
                if results.get('skipped'):
                    stats['skipped'] += 1
                if results.get('overwritten'):
                    stats['overwritten'] += 1
                if results.get('chi_file'):
                    stats['chi_files'].append(results['chi_file'])
                if results.get('xy_file'):
                    stats['xy_files'].append(results['xy_file'])
                if results.get('dat_file'):
                    stats['dat_files'].append(results['dat_file'])
                if results.get('npy_file'):
                    stats['npy_files'].append(results['npy_file'])
                if results.get('metadata_file'):
                    stats['metadata_files'].append(results['metadata_file'])
                if results.get('metadata_action') == "created":
                    stats['metadata_created'] += 1
                elif results.get('metadata_action') == "updated":
                    stats['metadata_updated'] += 1
                elif results.get('metadata_action') == "versioned":
                    stats['metadata_versioned'] += 1
            else:
                stats['failed'] += 1
                stats['failed_indices'].append(img_idx)

            if progress_callback and results['success']:
                progress_callback(
                    img_idx + 1, n_images,
                    f"Completed image {img_idx + 1}/{n_images}",
                )

            if n_images > 1:
                logger.info("-" * 80)

            if should_continue is not None and not should_continue():
                stats['cancelled'] = True
                logger.info(
                    f"Processing cancelled after image {img_idx + 1}/{n_images} from {base_name}"
                )
                break
                
        logger.info(
            f"Completed: {stats['processed']}/{n_images} images processed successfully "
            f"(skipped: {stats['skipped']})"
        )
        return stats
        
    def process_directory(self, 
                         input_directory: str,
                         export_chi: bool = True,
                         export_xy: bool = False,
                         export_dat: bool = False,
                         export_cake_npy: bool = True,
                         progress_callback=None,
                         export_metadata: bool = True) -> dict:
        """
        Process all supported diffraction image files in a directory.
        
        Args:
            input_directory: Directory containing detector image files
            export_chi: Export 1D patterns as CHI files
            export_xy: Export 1D patterns as XY files
            export_dat: Export 1D patterns as DAT files
            export_cake_npy: Export 2D cakes as NPY files
            export_metadata: Export source metadata as JSON
            progress_callback: Optional callback function
            
        Returns:
            Dictionary with overall statistics
        """
        input_path = Path(input_directory)
        all_files = [
            path
            for path in input_path.iterdir()
            if path.is_file() and has_supported_image_extension(path)
        ]
        
        if not all_files:
            extensions = ", ".join(DIFFRACTION_IMAGE_EXTENSIONS)
            logger.warning(f"No supported image files found in {input_directory}; expected: {extensions}")
            return {'file_sets': 0, 'total_processed': 0}
            
        # Group files
        file_groups = self.group_lambda_files([str(f) for f in all_files])
        
        logger.info(f"Found {len(file_groups)} complete file sets")
        
        overall_stats = {
            'file_sets': len(file_groups),
            'total_processed': 0,
            'total_failed': 0
        }
        
        # Process each file set
        for i, file_set in enumerate(file_groups):
            logger.info(f"Processing file set {i+1}/{len(file_groups)}")
            
            stats = self.process_file_set(
                file_set,
                export_chi=export_chi,
                export_xy=export_xy,
                export_dat=export_dat,
                export_cake_npy=export_cake_npy,
                export_metadata=export_metadata,
                progress_callback=progress_callback,
            )
            
            overall_stats['total_processed'] += stats['processed']
            overall_stats['total_failed'] += stats['failed']
            
        return overall_stats


if __name__ == "__main__":
    # Test the batch processor
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    import sys
    if len(sys.argv) < 4:
        print("Usage: python batch_processor.py <calibration.poni> <input_dir> <output_dir>")
        sys.exit(1)
        
    cal_file = sys.argv[1]
    input_dir = sys.argv[2]
    output_dir = sys.argv[3]
    
    processor = BatchProcessor(cal_file, output_dir)
    stats = processor.process_directory(input_dir)
    
    print(f"\nProcessing complete:")
    print(f"  File sets: {stats['file_sets']}")
    print(f"  Images processed: {stats['total_processed']}")
    print(f"  Failed: {stats['total_failed']}")
