#!/usr/bin/env python
"""
Dioptas Batch Processing GUI
Main application for automated batch processing with folder watching.
"""

import sys
import os
import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QCheckBox, QSpinBox, QGroupBox, QProgressBar, QMessageBox,
    QTabWidget, QListWidget
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QFont

from .file_watcher import FileWatcher
from .batch_processor import BatchProcessor
from .version import __version__


class ProcessingThread(QThread):
    """Thread for background processing to keep GUI responsive."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(dict)  # statistics
    error = pyqtSignal(str)
    
    def __init__(
        self,
        processor,
        file_set,
        export_chi,
        export_cake,
        apply_mask_to_chi,
        apply_mask_to_cake,
    ):
        super().__init__()
        self.processor = processor
        self.file_set = file_set
        self.export_chi = export_chi
        self.export_cake = export_cake
        self.apply_mask_to_chi = apply_mask_to_chi
        self.apply_mask_to_cake = apply_mask_to_cake
        
    def run(self):
        """Process files in background."""
        try:
            stats = self.processor.process_file_set(
                self.file_set,
                self.export_chi,
                self.export_cake,
                self.apply_mask_to_chi,
                self.apply_mask_to_cake,
                progress_callback=self._progress_callback
            )
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))
            
    def _progress_callback(self, current, total, message):
        """Forward progress updates to GUI."""
        self.progress.emit(current, total, message)


class DioptasBatchGUI(QMainWindow):
    """Main GUI window for Dioptas batch processing."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Dioptas Batch Processor v{__version__}")
        self.setGeometry(100, 100, 570, 750)
        
        # Initialize variables
        self.file_watcher = None
        self.processor = None
        self.processing_thread = None
        self.pending_files = []
        self.selected_files = []
        self.current_file_set = []
        self.current_mode = "idle"  # idle | batch | watch
        self.requested_input_files = 0
        self.requested_file_sets = 0
        self.completed_file_sets = 0
        
        # Setup logging
        self._setup_logging()
        
        # Create UI
        self._create_ui()
        
        # Timer to check for new files
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_for_files)
        
        # Load saved settings
        self._load_settings()
        
    def _setup_logging(self):
        """Setup logging to GUI console."""
        self.log_handler = logging.Handler()
        self.log_handler.setLevel(logging.INFO)
        
        # Will connect to text widget after UI creation
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                     datefmt='%H:%M:%S')
        self.log_handler.setFormatter(formatter)
        
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(self.log_handler)
        
    def _create_ui(self):
        """Create the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top header with version
        # header_label = QLabel(f"Dioptas Batch Processor v{__version__}")
        # header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        # main_layout.addWidget(header_label)
        
        # Mode selector tabs
        self.mode_tabs = QTabWidget()
        
        # Watch Mode Tab
        watch_tab = QWidget()
        watch_layout = QVBoxLayout(watch_tab)
        self._create_watch_mode_ui(watch_layout)
        self.mode_tabs.addTab(watch_tab, "Watch Mode (Auto)")
        
        # Batch Mode Tab
        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)
        self._create_batch_mode_ui(batch_layout)
        self.mode_tabs.addTab(batch_tab, "Batch Mode (Manual)")
        
        main_layout.addWidget(self.mode_tabs)
        
        # Shared configuration section
        config_group = QGroupBox("Processing Configuration")
        config_layout = QVBoxLayout()
        
        # Output directory
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_edit = QLineEdit()
        output_layout.addWidget(self.output_dir_edit)
        self.output_dir_btn = QPushButton("Browse...")
        self.output_dir_btn.clicked.connect(self._browse_output_dir)
        output_layout.addWidget(self.output_dir_btn)
        config_layout.addLayout(output_layout)
        
        # Calibration file
        cal_layout = QHBoxLayout()
        cal_layout.addWidget(QLabel("Calibration File (.poni):"))
        self.cal_file_edit = QLineEdit()
        cal_layout.addWidget(self.cal_file_edit)
        self.cal_file_btn = QPushButton("Browse...")
        self.cal_file_btn.clicked.connect(self._browse_cal_file)
        cal_layout.addWidget(self.cal_file_btn)
        config_layout.addLayout(cal_layout)
        
        # Mask file (optional)
        mask_layout = QHBoxLayout()
        mask_layout.addWidget(QLabel("Mask File (optional):"))
        self.mask_file_edit = QLineEdit()
        mask_layout.addWidget(self.mask_file_edit)
        self.mask_file_btn = QPushButton("Browse...")
        self.mask_file_btn.clicked.connect(self._browse_mask_file)
        mask_layout.addWidget(self.mask_file_btn)
        config_layout.addLayout(mask_layout)
        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
        # Processing Options
        options_group = QGroupBox("Processing Options")
        options_layout = QVBoxLayout()
        
        # Integration controls (side by side)
        integration_layout = QHBoxLayout()
        integration_layout.addWidget(QLabel("Integration Points (1D):"))
        self.integration_points_spin = QSpinBox()
        self.integration_points_spin.setRange(500, 10000)
        self.integration_points_spin.setValue(4857)
        self.integration_points_spin.setSingleStep(100)
        integration_layout.addWidget(self.integration_points_spin)
        integration_layout.addSpacing(20)
        integration_layout.addWidget(QLabel("Azimuth Bins (2D):"))
        self.azimuth_points_spin = QSpinBox()
        self.azimuth_points_spin.setRange(100, 2000)
        self.azimuth_points_spin.setValue(360)
        self.azimuth_points_spin.setSingleStep(10)
        integration_layout.addWidget(self.azimuth_points_spin)
        integration_layout.addStretch()
        options_layout.addLayout(integration_layout)
        
        # Export options
        export_layout = QHBoxLayout()
        self.export_chi_cb = QCheckBox("Export CHI files (1D patterns)")
        self.export_chi_cb.setChecked(True)
        export_layout.addWidget(self.export_chi_cb)
        
        self.export_npy_cb = QCheckBox("Export NPY files (2D cakes)")
        self.export_npy_cb.setChecked(True)
        export_layout.addWidget(self.export_npy_cb)
        options_layout.addLayout(export_layout)

        # Mask application options
        mask_apply_layout = QHBoxLayout()
        self.apply_mask_to_chi_cb = QCheckBox("Apply mask to CHI (1D)")
        self.apply_mask_to_chi_cb.setChecked(True)
        mask_apply_layout.addWidget(self.apply_mask_to_chi_cb)

        self.apply_mask_to_cake_cb = QCheckBox("Apply mask to cake (2D)")
        self.apply_mask_to_cake_cb.setChecked(False)
        mask_apply_layout.addWidget(self.apply_mask_to_cake_cb)
        options_layout.addLayout(mask_apply_layout)
        
        # Overwrite option
        overwrite_layout = QHBoxLayout()
        self.overwrite_cb = QCheckBox("Overwrite existing files")
        self.overwrite_cb.setChecked(False)
        overwrite_layout.addWidget(self.overwrite_cb)
        overwrite_layout.addStretch()
        options_layout.addLayout(overwrite_layout)
        
        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)
        
        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        self.status_label = QLabel("Status: Idle")
        self.status_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        progress_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.stats_label = QLabel("Files processed: 0 | Pending: 0")
        progress_layout.addWidget(self.stats_label)
        
        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)
        
        # Log console
        log_group = QGroupBox("Processing Log")
        log_layout = QVBoxLayout()
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(200)
        self.log_console.setStyleSheet("background-color: #f5f5f5; color: #000000; font-family: monospace;")
        log_layout.addWidget(self.log_console)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_console.clear)
        log_layout.addWidget(clear_btn)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # Connect log handler to text widget
        self.log_handler.emit = lambda record: self._append_log(
            self.log_handler.format(record)
        )
        
    def _create_watch_mode_ui(self, layout):
        """Create UI for watch mode."""
        info_label = QLabel("Monitor a folder and automatically process new files as they appear.")
        info_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(info_label)
        
        # Watch directory
        watch_layout = QHBoxLayout()
        watch_layout.addWidget(QLabel("Watch Directory:"))
        self.watch_dir_edit = QLineEdit()
        watch_layout.addWidget(self.watch_dir_edit)
        self.watch_dir_btn = QPushButton("Browse...")
        self.watch_dir_btn.clicked.connect(self._browse_watch_dir)
        watch_layout.addWidget(self.watch_dir_btn)
        layout.addLayout(watch_layout)
        
        # Control buttons for watch mode
        control_layout = QHBoxLayout()
        self.start_watch_btn = QPushButton("Start Watching")
        self.start_watch_btn.clicked.connect(self._start_watching)
        self.start_watch_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        control_layout.addWidget(self.start_watch_btn)
        
        self.stop_watch_btn = QPushButton("Stop Watching")
        self.stop_watch_btn.clicked.connect(self._stop_watching)
        self.stop_watch_btn.setEnabled(False)
        self.stop_watch_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 8px; }")
        control_layout.addWidget(self.stop_watch_btn)
        
        layout.addLayout(control_layout)
        layout.addStretch()
        
    def _create_batch_mode_ui(self, layout):
        """Create UI for batch mode."""
        info_label = QLabel("Select specific files to process immediately without folder watching.")
        info_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(info_label)
        
        # File selection
        file_select_layout = QHBoxLayout()
        self.select_files_btn = QPushButton("Select Files...")
        self.select_files_btn.clicked.connect(self._select_files)
        self.select_files_btn.setStyleSheet("QPushButton { padding: 8px; }")
        file_select_layout.addWidget(self.select_files_btn)
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        file_select_layout.addWidget(self.clear_selection_btn)
        
        file_select_layout.addStretch()
        layout.addLayout(file_select_layout)
        
        # File list
        list_label = QLabel("Selected Files:")
        layout.addWidget(list_label)
        
        self.file_list_widget = QListWidget()
        self.file_list_widget.setMaximumHeight(150)
        layout.addWidget(self.file_list_widget)
        
        # Process button for batch mode
        self.process_batch_btn = QPushButton("Process Selected Files")
        self.process_batch_btn.clicked.connect(self._process_batch)
        self.process_batch_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 10px; }")
        self.process_batch_btn.setEnabled(False)
        layout.addWidget(self.process_batch_btn)
        
        layout.addStretch()
        
    def _append_log(self, message):
        """Append message to log console."""
        self.log_console.append(message)
        self.log_console.verticalScrollBar().setValue(
            self.log_console.verticalScrollBar().maximum()
        )
        
    def _select_files(self):
        """Select files for batch processing."""
        # Get last used directory from settings, or use current output dir if set
        settings = QSettings("Dioptas", "BatchProcessor")
        last_file_dir = settings.value("last_file_dir", "")
        
        # If no last directory, try to use current output directory
        if not last_file_dir and self.output_dir_edit.text():
            last_file_dir = self.output_dir_edit.text()
        
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Lambda Detector Files",
            last_file_dir,
            "HDF5 Files (*.h5 *.nxs);;All Files (*)"
        )
        if file_paths:
            self.selected_files = file_paths
            self.file_list_widget.clear()
            for path in file_paths:
                self.file_list_widget.addItem(Path(path).name)
            self.process_batch_btn.setEnabled(len(file_paths) > 0)
            self._append_log(f"Selected {len(file_paths)} files")
            
            # Get the directory of the selected files
            file_directory = str(Path(file_paths[0]).parent)
            
            # Automatically set output directory to same folder as h5 files
            self.output_dir_edit.setText(file_directory)
            
            # Save the directory for next time
            settings.setValue("last_file_dir", file_directory)
            self._save_settings()
            
    def _clear_selection(self):
        """Clear file selection."""
        self.selected_files = []
        self.file_list_widget.clear()
        self.process_batch_btn.setEnabled(False)
        self._append_log("File selection cleared")
        
    def _load_settings(self):
        """Load saved settings."""
        settings = QSettings("Dioptas", "BatchProcessor")
        self.output_dir_edit.setText(settings.value("output_dir", ""))
        self.cal_file_edit.setText(settings.value("cal_file", ""))
        self.mask_file_edit.setText(settings.value("mask_file", ""))
        self.watch_dir_edit.setText(settings.value("watch_dir", ""))
        self.apply_mask_to_chi_cb.setChecked(settings.value("apply_mask_to_chi", True, type=bool))
        self.apply_mask_to_cake_cb.setChecked(settings.value("apply_mask_to_cake", False, type=bool))
        
    def _save_settings(self):
        """Save current settings."""
        settings = QSettings("Dioptas", "BatchProcessor")
        settings.setValue("output_dir", self.output_dir_edit.text())
        settings.setValue("cal_file", self.cal_file_edit.text())
        settings.setValue("mask_file", self.mask_file_edit.text())
        settings.setValue("watch_dir", self.watch_dir_edit.text())
        settings.setValue("apply_mask_to_chi", self.apply_mask_to_chi_cb.isChecked())
        settings.setValue("apply_mask_to_cake", self.apply_mask_to_cake_cb.isChecked())
    
    def _browse_watch_dir(self):
        """Browse for watch directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Watch Directory")
        if dir_path:
            self.watch_dir_edit.setText(dir_path)
            self._save_settings()
            
    def _browse_output_dir(self):
        """Browse for output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
            self._save_settings()
            
    def _browse_cal_file(self):
        """Browse for calibration file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Calibration File", "", "PONI Files (*.poni);;All Files (*)"
        )
        if file_path:
            self.cal_file_edit.setText(file_path)
            self._save_settings()
            
    def _browse_mask_file(self):
        """Browse for mask file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Mask File", "", "Mask Files (*.mask *.tif *.tiff);;All Files (*)"
        )
        if file_path:
            self.mask_file_edit.setText(file_path)
            self._save_settings()
            
    def _validate_config(self, check_watch_dir=False):
        """Validate configuration before starting."""
        if check_watch_dir and not self.watch_dir_edit.text():
            QMessageBox.warning(self, "Configuration Error", "Please select a watch directory")
            return False
        if not self.output_dir_edit.text():
            QMessageBox.warning(self, "Configuration Error", "Please select an output directory")
            return False
        if not self.cal_file_edit.text():
            QMessageBox.warning(self, "Configuration Error", "Please select a calibration file")
            return False
        if not Path(self.cal_file_edit.text()).exists():
            QMessageBox.warning(self, "Configuration Error", "Calibration file does not exist")
            return False
        return True
        
    def _process_batch(self):
        """Process selected files in batch mode."""
        if not self.selected_files:
            QMessageBox.warning(self, "No Files", "Please select files to process")
            return
            
        if not self._validate_config(check_watch_dir=False):
            return
            
        try:
            # Initialize processor
            mask_file = self.mask_file_edit.text() if self.mask_file_edit.text() else None
            self.processor = BatchProcessor(
                calibration_file=self.cal_file_edit.text(),
                output_directory=self.output_dir_edit.text(),
                mask_file=mask_file,
                num_points=self.integration_points_spin.value(),
                cake_azimuth_points=self.azimuth_points_spin.value(),
                overwrite=self.overwrite_cb.isChecked()
            )
            
            # Group selected files
            file_groups = self.processor.group_lambda_files(self.selected_files)
            
            if not file_groups:
                QMessageBox.warning(
                    self, 
                    "No Files to Process",
                    "No valid files found to process.\n"
                    "Multi-module Lambda files need m1, m2, m3 for each dataset."
                )
                return
                
            self._append_log(f"=== Processing {len(file_groups)} file set(s) ===")
            self.current_mode = "batch"
            self.requested_input_files = len(self.selected_files)
            self.requested_file_sets = len(file_groups)
            self.completed_file_sets = 0
            
            # Disable controls
            self.process_batch_btn.setEnabled(False)
            self.select_files_btn.setEnabled(False)
            
            # Process files
            self.pending_files = [f for group in file_groups for f in group]
            self._update_stats_label()
            self._process_next_batch()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            QMessageBox.critical(self, "Error", f"Failed to start batch processing:\n{str(e)}\n\nSee log for details.")
            logging.error(f"Batch processing error: {e}")
            logging.error(f"Traceback:\n{error_details}")
            self._append_log(f"ERROR: {str(e)}")
            self.process_batch_btn.setEnabled(True)
            self.select_files_btn.setEnabled(True)
    
    def _start_watching(self):
        """Start file watching and auto-processing."""
        if not self._validate_config(check_watch_dir=True):
            return
            
        try:
            # Initialize processor
            mask_file = self.mask_file_edit.text() if self.mask_file_edit.text() else None
            self.processor = BatchProcessor(
                calibration_file=self.cal_file_edit.text(),
                output_directory=self.output_dir_edit.text(),
                mask_file=mask_file,
                num_points=self.integration_points_spin.value(),
                cake_azimuth_points=self.azimuth_points_spin.value(),
                overwrite=self.overwrite_cb.isChecked()
            )
            self.current_mode = "watch"
            self.requested_input_files = 0
            self.requested_file_sets = 0
            self.completed_file_sets = 0
            
            # Initialize file watcher
            self.file_watcher = FileWatcher(self.watch_dir_edit.text())
            self.file_watcher.start()
            
            # Check for existing files in the directory and queue them
            watch_path = Path(self.watch_dir_edit.text())
            existing_files = []
            for pattern in ['*.h5', '*.nxs']:
                existing_files.extend([str(f) for f in watch_path.glob(pattern)])
            
            if existing_files:
                # Check which files haven't been processed yet
                unprocessed_files = []
                output_dir = Path(self.output_dir_edit.text())
                for file_path in existing_files:
                    base_name = Path(file_path).stem
                    chi_path = output_dir / f"{base_name}.chi"
                    if not chi_path.exists():
                        unprocessed_files.append(file_path)
                
                if unprocessed_files:
                    self._append_log(f"Found {len(unprocessed_files)} existing unprocessed files")
                    self.pending_files.extend(unprocessed_files)
                    # Start processing immediately
                    self._process_next_batch()
            
            # Start timer to check for files
            self.check_timer.start(1000)  # Check every second
            
            # Update UI
            self.start_watch_btn.setEnabled(False)
            self.stop_watch_btn.setEnabled(True)
            self.status_label.setText("Status: Watching for files...")
            self.status_label.setStyleSheet("color: green;")
            
            self._append_log("=== Auto-processing started ===")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start: {str(e)}")
            logging.error(f"Failed to start: {e}")
            
    def _stop_watching(self):
        """Stop file watching."""
        if self.file_watcher:
            self.file_watcher.stop()
            self.file_watcher = None
            
        self.check_timer.stop()
        
        # Update UI
        self.start_watch_btn.setEnabled(True)
        self.stop_watch_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("color: gray;")
        
        self._append_log("=== Auto-processing stopped ===")
        
    def _check_for_files(self):
        """Check for new complete files and process them."""
        if not self.file_watcher or self.processing_thread is not None:
            return
            
        # Get completed files
        completed_files = self.file_watcher.get_completed_files()
        
        if completed_files:
            self.pending_files.extend(completed_files)
            self._process_next_batch()
            
    def _process_next_batch(self):
        """Process the next batch of files."""
        if not self.pending_files or self.processing_thread is not None:
            return
            
        # Group files into sets
        file_groups = self.processor.group_lambda_files(self.pending_files)
        
        if not file_groups:
            return
            
        # Process first complete set
        file_set = file_groups[0]
        self.current_file_set = file_set
        
        # Remove processed files from pending
        for f in file_set:
            if f in self.pending_files:
                self.pending_files.remove(f)
                
        # Start processing thread
        self.processing_thread = ProcessingThread(
            self.processor,
            file_set,
            self.export_chi_cb.isChecked(),
            self.export_npy_cb.isChecked(),
            self.apply_mask_to_chi_cb.isChecked(),
            self.apply_mask_to_cake_cb.isChecked(),
        )
        self.processing_thread.progress.connect(self._update_progress)
        self.processing_thread.finished.connect(self._processing_finished)
        self.processing_thread.error.connect(self._processing_error)
        self.processing_thread.start()
        self._append_log("-" * 80)
        self._append_log(f"Starting file set: {Path(file_set[0]).stem}")
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v/%m images")
        self.status_label.setText(f"Status: Processing {Path(file_set[0]).stem}...")
        self._update_stats_label()
        
    def _update_progress(self, current, total, message):
        """Update progress bar."""
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        if self.current_mode == "batch" and self.requested_file_sets:
            current_set_idx = self.completed_file_sets + 1
            self.status_label.setText(
                f"Status: File set {current_set_idx}/{self.requested_file_sets} | {message}"
            )
        else:
            self.status_label.setText(f"Status: {message}")
        
    def _processing_finished(self, stats):
        """Handle processing completion."""
        self.processing_thread = None
        self.completed_file_sets += 1
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        
        self._append_log(
            f"Completed: {stats['processed']}/{stats['total_images']} images "
            f"(skipped: {stats.get('skipped', 0)})"
        )
        
        # Update stats
        self._update_stats_label(stats)
        
        # Process next batch if available
        if self.pending_files:
            self._process_next_batch()
        else:
            # Check which mode we're in
            if self.file_watcher and self.file_watcher.is_running:
                self.status_label.setText("Status: Watching for files...")
            else:
                self.status_label.setText("Status: All files processed")
                # Re-enable batch mode controls
                self.process_batch_btn.setEnabled(len(self.selected_files) > 0)
                self.select_files_btn.setEnabled(True)
            
    def _processing_error(self, error_msg):
        """Handle processing error."""
        self.processing_thread = None
        self.progress_bar.setValue(0)
        self._append_log(f"ERROR: {error_msg}")
        self.status_label.setText("Status: Error occurred")
        self._update_stats_label()

    def _update_stats_label(self, last_stats=None):
        """Update summary stats text based on current mode."""
        pending_count = len(self.pending_files)
        if self.current_mode == "batch" and self.requested_file_sets:
            if last_stats:
                last_batch_text = (
                    f"Last batch: {last_stats.get('processed', 0)}/{last_stats.get('total_images', 0)} images"
                )
            else:
                last_batch_text = "Last batch: -"
            self.stats_label.setText(
                f"Requested files: {self.requested_input_files} | "
                f"File sets: {self.completed_file_sets}/{self.requested_file_sets} | "
                f"{last_batch_text} | Pending files: {pending_count}"
            )
            return

        if last_stats:
            self.stats_label.setText(
                f"Last batch: {last_stats.get('processed', 0)}/{last_stats.get('total_images', 0)} images | "
                f"Pending files: {pending_count}"
            )
        else:
            self.stats_label.setText(f"Files processed: 0 | Pending: {pending_count}")
        
    def closeEvent(self, event):
        """Handle window close."""
        if self.file_watcher:
            self._stop_watching()
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = DioptasBatchGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
