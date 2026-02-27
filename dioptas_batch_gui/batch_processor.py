#!/usr/bin/env python
"""
Batch Processor Module for Dioptas Integration
Processes Lambda detector files and exports to CHI/XY/DAT and NPY formats.
"""

import os
import re
import logging
import numpy as np
from pathlib import Path
from glob import glob
from typing import List, Tuple, Optional
import h5py

# Dioptas imports
from dioptas.model.Configuration import Configuration
from dioptas.model.loader import LambdaLoader

logger = logging.getLogger(__name__)


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
        self.output_directory = Path(output_directory).expanduser().resolve()
        self.mask_file = mask_file
        self._mask_available = False
        self._mask_shape_loaded = None
        self.num_points = num_points
        self.integration_method = integration_method
        self.cake_azimuth_points = cake_azimuth_points
        self.overwrite = overwrite
        
        # Create output directory if it doesn't exist
        self.output_directory.mkdir(parents=True, exist_ok=True)
        
        # Initialize Dioptas configuration
        self.config = Configuration()
        self._load_calibration()
        self._load_mask()
        
        # Configure integration parameters
        self._apply_integration_settings()
        self.config.auto_integrate_cake = True  # Enable cake integration
        
        logger.info("Batch processor initialized")
        logger.info(f"Calibration: {calibration_file}")
        logger.info(f"Output: {output_directory}")
        logger.info(f"Integration points: {num_points}")
        logger.info(f"CAKE radial points: {self._cake_radial_points()}")

    def _cake_radial_points(self) -> int:
        """CAKE radial bins are defined as 2x the 1D integration points."""
        return int(self.num_points) * 2

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
        Single HDF5 files are treated as individual file sets.
        
        Args:
            file_list: List of file paths
            
        Returns:
            List of file groups, where each group has 3 files (multi-module) or 1 file (single)
        """
        multi_module_groups = {}
        single_files = []
        
        for file_path in file_list:
            # Check if this is a multi-module Lambda file (has _m1, _m2, or _m3)
            if re.search(r'_m[1-3](_part\d+)?\.(nxs|h5)$', file_path):
                # Multi-module Lambda file
                base_name = re.sub(r'_m[1-3](_part\d+)?\.(nxs|h5)$', '', file_path)
                
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
        Get number of images in a Lambda file set.
        
        Args:
            file_set: List of 3 Lambda files
            
        Returns:
            Number of images in the dataset
        """
        try:
            with h5py.File(file_set[0], 'r') as f:
                data_path = 'entry/instrument/detector/data'
                if data_path in f:
                    return f[data_path].shape[0]
        except Exception as e:
            logger.error(f"Error reading image count: {e}")
            
        return 0

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
        }
        
    def process_lambda_image(self, 
                            file_set: List[str], 
                            image_index: int,
                            base_output_name: str,
                            export_chi: bool = True,
                            export_xy: bool = False,
                            export_dat: bool = False,
                            export_cake_npy: bool = True,
                            apply_mask_to_chi: bool = True,
                            apply_mask_to_cake: bool = False) -> dict:
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
            'skipped': False,
        }
        paths = self._build_output_paths(base_output_name)
        
        try:
            # Fast path: skip opening HDF5/integration when all selected outputs already exist.
            chi_exists = paths["chi_path"].exists()
            xy_exists = paths["xy_path"].exists()
            dat_exists = paths["dat_path"].exists()
            cake_files_exist = (
                paths["int_path"].exists()
                and paths["tth_path"].exists()
                and paths["azi_path"].exists()
            )
            cake_exists = cake_files_exist and self._cake_matches_requested_resolution(paths)
            chi_ready = (not export_chi) or chi_exists
            xy_ready = (not export_xy) or xy_exists
            dat_ready = (not export_dat) or dat_exists
            cake_ready = (not export_cake_npy) or cake_exists
            need_chi_processing = export_chi and (self.overwrite or not chi_exists)
            need_xy_processing = export_xy and (self.overwrite or not xy_exists)
            need_dat_processing = export_dat and (self.overwrite or not dat_exists)
            need_cake_processing = export_cake_npy and (self.overwrite or not cake_exists)
            need_1d_processing = need_chi_processing or need_xy_processing or need_dat_processing

            if not self.overwrite and chi_ready and xy_ready and dat_ready and cake_ready:
                existing_dims = self._get_existing_cake_dims(paths) if export_cake_npy else None
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
                            import shutil
                            shutil.copy2(self.calibration_file, paths["poni_dest"])
                            logger.debug(f"Copied poni file to {paths['cake_folder']}")
                        except Exception as e:
                            logger.warning(f"Failed to copy poni file: {e}")

                logger.info(
                    f"Skipping image {image_index}: outputs already exist for {base_output_name}"
                )
                if existing_dims is not None:
                    logger.info(
                        "Using existing CAKE files with bins: "
                        f"intensity_shape={existing_dims[0]}, tth={existing_dims[1]}, azi={existing_dims[2]} "
                        f"(requested tth={self._cake_radial_points()}, azi={self.cake_azimuth_points})"
                    )
                results['success'] = True
                results['skipped'] = True
                return results

            # Check if this is a multi-module Lambda file or single file
            if len(file_set) == 3:
                # Multi-module Lambda detector
                lambda_loader = LambdaLoader.LambdaImage(file_list=file_set)
                img_data = lambda_loader.get_image(image_index)
                
                # Load image into Dioptas
                self.config.img_model.blockSignals(True)
                self.config.img_model.img_data = img_data
                self.config.img_model.blockSignals(False)
            else:
                # Single HDF5 file - Dioptas' load method handles everything
                self.config.img_model.blockSignals(True)
                self.config.img_model.load(file_set[0], image_index)
                self.config.img_model.blockSignals(False)

            if self._mask_available and (
                (need_1d_processing and apply_mask_to_chi)
                or (need_cake_processing and apply_mask_to_cake)
            ):
                self._ensure_mask_loaded_for_current_image()

            # Re-apply integration settings in case Dioptas resets them on load.
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
                    self.config.save_pattern(str(chi_path))
                    results['chi_file'] = str(chi_path)
                    logger.info(f"Saved CHI file: {chi_path.resolve()}")

            if export_xy:
                xy_path = paths["xy_path"]

                if not need_xy_processing:
                    logger.info(f"Skipping existing XY file: {xy_path.resolve()}")
                    results['xy_file'] = str(xy_path)
                    results['skipped'] = True
                else:
                    self.config.save_pattern(str(xy_path))
                    results['xy_file'] = str(xy_path)
                    logger.info(f"Saved XY file: {xy_path.resolve()}")

            if export_dat:
                dat_path = paths["dat_path"]

                if not need_dat_processing:
                    logger.info(f"Skipping existing DAT file: {dat_path.resolve()}")
                    results['dat_file'] = str(dat_path)
                    results['skipped'] = True
                else:
                    self.config.save_pattern(str(dat_path))
                    results['dat_file'] = str(dat_path)
                    logger.info(f"Saved DAT file: {dat_path.resolve()}")
                
            # Export cake as separate NPY files (intensity, azimuth/chi, two-theta)
            # Save in a subfolder: filename-param/
            if export_cake_npy:
                # Create subfolder for cake files: filename-param
                cake_folder = paths["cake_folder"]
                cake_folder.mkdir(parents=True, exist_ok=True)
                
                # Copy poni file to param folder
                import shutil
                poni_dest = paths["poni_dest"]
                if not poni_dest.exists() or self.overwrite:
                    try:
                        shutil.copy2(self.calibration_file, poni_dest)
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

                    np.save(str(int_path), intensity_cake)
                    np.save(str(tth_path), tth_cake)
                    np.save(str(azi_path), chi_cake)
                    results['npy_files'] = [str(int_path), str(tth_path), str(azi_path)]
                    results['npy_file'] = str(int_path)
                    logger.info(
                        "Saved cake files: "
                        f"{int_path.resolve()}, {tth_path.resolve()}, {azi_path.resolve()}"
                    )
                
            results['success'] = True
            
        except Exception as e:
            logger.error(f"Error processing image {image_index}: {e}")
            results['error'] = str(e)
            
        return results
        
    def process_file_set(self, 
                        file_set: List[str],
                        export_chi: bool = True,
                        export_xy: bool = False,
                        export_dat: bool = False,
                        export_cake_npy: bool = True,
                        apply_mask_to_chi: bool = True,
                        apply_mask_to_cake: bool = False,
                        progress_callback=None) -> dict:
        """
        Process all images in a Lambda file set.
        
        Args:
            file_set: List of 3 Lambda files
            export_chi: Export 1D patterns as CHI files
            export_xy: Export 1D patterns as XY files
            export_dat: Export 1D patterns as DAT files
            export_cake_npy: Export 2D cakes as NPY files
            apply_mask_to_chi: Apply mask during CHI integration
            apply_mask_to_cake: Apply mask during cake integration
            progress_callback: Optional callback function(current, total, status_msg)
            
        Returns:
            Dictionary with processing statistics
        """
        stats = {
            'total_images': 0,
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'chi_files': [],
            'xy_files': [],
            'dat_files': [],
            'npy_files': []
        }
        
        # Get base name for output files
        base_name = Path(file_set[0]).stem
        base_name = re.sub(r'_m\d+(_part\d+)?$', '', base_name)
        
        # Get number of images
        n_images = self.get_image_count(file_set)
        stats['total_images'] = n_images
        
        if n_images == 0:
            logger.error(f"No images found in file set")
            return stats
            
        logger.info(f"Processing {n_images} images from {base_name}")
        
        # Process each image
        for img_idx in range(n_images):
            if progress_callback:
                progress_callback(img_idx + 1, n_images, f"Processing image {img_idx + 1}/{n_images}")
                
            results = self.process_lambda_image(
                file_set,
                img_idx,
                base_name,
                export_chi,
                export_xy,
                export_dat,
                export_cake_npy,
                apply_mask_to_chi,
                apply_mask_to_cake,
            )
            
            if results['success']:
                stats['processed'] += 1
                if results.get('skipped'):
                    stats['skipped'] += 1
                if results.get('chi_file'):
                    stats['chi_files'].append(results['chi_file'])
                if results.get('xy_file'):
                    stats['xy_files'].append(results['xy_file'])
                if results.get('dat_file'):
                    stats['dat_files'].append(results['dat_file'])
                if results.get('npy_file'):
                    stats['npy_files'].append(results['npy_file'])
            else:
                stats['failed'] += 1
                
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
                         progress_callback=None) -> dict:
        """
        Process all Lambda files in a directory.
        
        Args:
            input_directory: Directory containing Lambda files
            export_chi: Export 1D patterns as CHI files
            export_xy: Export 1D patterns as XY files
            export_dat: Export 1D patterns as DAT files
            export_cake_npy: Export 2D cakes as NPY files
            progress_callback: Optional callback function
            
        Returns:
            Dictionary with overall statistics
        """
        # Find all .nxs and .h5 files
        input_path = Path(input_directory)
        nxs_files = list(input_path.glob("*.nxs"))
        h5_files = list(input_path.glob("*.h5"))
        all_files = nxs_files + h5_files
        
        if not all_files:
            logger.warning(f"No .nxs or .h5 files found in {input_directory}")
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
