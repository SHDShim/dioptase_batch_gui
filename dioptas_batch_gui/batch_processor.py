#!/usr/bin/env python
"""
Batch Processor Module for Dioptas Integration
Processes Lambda detector files and exports to CHI and NPY formats.
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
    Exports to CHI files (1D patterns) and NPY files (2D cake images).
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
        self.output_directory = Path(output_directory)
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
        self.config.integration_rad_points = num_points
        self.config.cake_azimuth_points = cake_azimuth_points
        self.config.auto_integrate_cake = True  # Enable cake integration
        
        logger.info("Batch processor initialized")
        logger.info(f"Calibration: {calibration_file}")
        logger.info(f"Output: {output_directory}")
        logger.info(f"Integration points: {num_points}")
        
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
        
    def process_lambda_image(self, 
                            file_set: List[str], 
                            image_index: int,
                            base_output_name: str,
                            export_chi: bool = True,
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
            export_cake_npy: Export 2D cake as NPY file
            apply_mask_to_chi: Apply mask during CHI integration
            apply_mask_to_cake: Apply mask during cake integration
            
        Returns:
            Dictionary with processing results
        """
        results = {'success': False, 'chi_file': None, 'npy_file': None}
        
        try:
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

            if self._mask_available and (apply_mask_to_chi or apply_mask_to_cake):
                self._ensure_mask_loaded_for_current_image()
            
            # Integrate 1D (CHI) with optional mask
            self.config.use_mask = bool(self._mask_available and apply_mask_to_chi)
            self.config.integrate_image_1d()

            # Integrate 2D cake with optional mask
            if export_cake_npy:
                self.config.use_mask = bool(self._mask_available and apply_mask_to_cake)
                self.config.integrate_image_2d()
            
            # Export CHI file (1D pattern) - use base filename without _0000 suffix
            if export_chi:
                chi_filename = f"{base_output_name}.chi"
                chi_path = self.output_directory / chi_filename
                
                # Check if file exists and skip if not overwriting
                if not self.overwrite and chi_path.exists():
                    logger.info(f"Skipping existing CHI file: {chi_filename}")
                    results['chi_file'] = str(chi_path)
                    results['skipped'] = True
                else:
                    self.config.save_pattern(str(chi_path))
                    results['chi_file'] = str(chi_path)
                    logger.debug(f"Saved CHI: {chi_filename}")
                
            # Export cake as separate NPY files (intensity, azimuth/chi, two-theta)
            # Save in a subfolder: filename-param/
            if export_cake_npy:
                # Get cake data from Dioptas
                # cake_img = 2D intensity array (azimuth x radial)
                # cake_tth = 1D array of 2-theta values (radial axis)
                # cake_azi = 1D array of azimuthal/chi values (azimuth axis)
                intensity_cake = self.config.calibration_model.cake_img
                tth_cake = self.config.calibration_model.cake_tth
                chi_cake = self.config.calibration_model.cake_azi
                
                # Create subfolder for cake files: filename-param
                cake_folder = self.output_directory / f"{base_output_name}-param"
                cake_folder.mkdir(parents=True, exist_ok=True)
                
                # Copy poni file to param folder
                import shutil
                poni_dest = cake_folder / Path(self.calibration_file).name
                if not poni_dest.exists() or self.overwrite:
                    try:
                        shutil.copy2(self.calibration_file, poni_dest)
                        logger.debug(f"Copied poni file to {cake_folder}")
                    except Exception as e:
                        logger.warning(f"Failed to copy poni file: {e}")
                
                # Save as 3 separate files matching user's format
                int_filename = f"{base_output_name}.int.cake.npy"
                tth_filename = f"{base_output_name}.tth.cake.npy"
                azi_filename = f"{base_output_name}.azi.cake.npy"
                
                int_path = cake_folder / int_filename
                tth_path = cake_folder / tth_filename
                azi_path = cake_folder / azi_filename
                
                # Check if files exist and skip if not overwriting
                if not self.overwrite and int_path.exists() and azi_path.exists() and tth_path.exists():
                    logger.info(f"Skipping existing cake files: {base_output_name}-param/{base_output_name}.*.cake.npy")
                    results['npy_files'] = [str(int_path), str(tth_path), str(azi_path)]
                    results['skipped'] = True
                else:
                    np.save(str(int_path), intensity_cake)
                    np.save(str(tth_path), tth_cake)
                    np.save(str(azi_path), chi_cake)
                    results['npy_files'] = [str(int_path), str(tth_path), str(azi_path)]
                    logger.debug(f"Saved cake files in {base_output_name}-param/: {int_filename}, {tth_filename}, {azi_filename}")
                
            results['success'] = True
            
        except Exception as e:
            logger.error(f"Error processing image {image_index}: {e}")
            results['error'] = str(e)
            
        return results
        
    def process_file_set(self, 
                        file_set: List[str],
                        export_chi: bool = True,
                        export_cake_npy: bool = True,
                        apply_mask_to_chi: bool = True,
                        apply_mask_to_cake: bool = False,
                        progress_callback=None) -> dict:
        """
        Process all images in a Lambda file set.
        
        Args:
            file_set: List of 3 Lambda files
            export_chi: Export 1D patterns as CHI files
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
            'chi_files': [],
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
                export_cake_npy,
                apply_mask_to_chi,
                apply_mask_to_cake,
            )
            
            if results['success']:
                stats['processed'] += 1
                if results.get('chi_file'):
                    stats['chi_files'].append(results['chi_file'])
                if results.get('npy_file'):
                    stats['npy_files'].append(results['npy_file'])
            else:
                stats['failed'] += 1
                
        logger.info(f"Completed: {stats['processed']}/{n_images} images processed successfully")
        return stats
        
    def process_directory(self, 
                         input_directory: str,
                         export_chi: bool = True,
                         export_cake_npy: bool = True,
                         progress_callback=None) -> dict:
        """
        Process all Lambda files in a directory.
        
        Args:
            input_directory: Directory containing Lambda files
            export_chi: Export 1D patterns as CHI files
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
