#!/usr/bin/env python
"""
Dioptas Batch Processing GUI
Main application for automated batch processing with folder watching.
"""

import sys
import os
import logging
import re
from html import escape
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QCheckBox, QGroupBox, QProgressBar, QMessageBox, QRadioButton,
    QTabWidget, QSizePolicy, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QGridLayout,
    QHeaderView
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QSettings, Qt
from PyQt6.QtGui import QFont, QIcon, QFontMetrics

from .file_watcher import FileWatcher
from .batch_processor import BatchProcessor
from .version import __version__

FIXED_AZIMUTH_BINS = 360


def load_app_icon():
    """Return the packaged application icon, preferring platform-native formats."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    icon = QIcon()

    for icon_name in ("dbg.icns", "dbg.ico"):
        icon_path = assets_dir / icon_name
        if icon_path.exists():
            icon.addFile(str(icon_path))

    return icon


class ProcessingThread(QThread):
    """Thread for background processing to keep GUI responsive."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    result_ready = pyqtSignal(dict)  # statistics
    error = pyqtSignal(str)
    integration_points_estimated = pyqtSignal(int)
    
    def __init__(
        self,
        processor,
        file_set,
        export_chi,
        export_xy,
        export_dat,
        export_cake,
        apply_mask_to_chi,
        apply_mask_to_cake,
    ):
        super().__init__()
        self.processor = processor
        self.file_set = file_set
        self.export_chi = export_chi
        self.export_xy = export_xy
        self.export_dat = export_dat
        self.export_cake = export_cake
        self.apply_mask_to_chi = apply_mask_to_chi
        self.apply_mask_to_cake = apply_mask_to_cake
        
    def run(self):
        """Process files in background."""
        try:
            stats = self.processor.process_file_set(
                self.file_set,
                self.export_chi,
                self.export_xy,
                self.export_dat,
                self.export_cake,
                self.apply_mask_to_chi,
                self.apply_mask_to_cake,
                progress_callback=self._progress_callback,
                estimate_callback=self._estimate_callback,
            )
            self.result_ready.emit(stats)
        except Exception as e:
            self.error.emit(str(e))
            
    def _progress_callback(self, current, total, message):
        """Forward progress updates to GUI."""
        self.progress.emit(current, total, message)

    def _estimate_callback(self, num_points):
        """Forward integration-point estimates to the GUI."""
        self.integration_points_estimated.emit(int(num_points))


class DioptasBatchGUI(QMainWindow):
    """Main GUI window for Dioptas batch processing."""
    log_message = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Dioptas Bach GUI v{__version__}")
        self.setGeometry(100, 100, 1500, 900)
        self._set_window_icon()
        
        # Initialize variables
        self.file_watcher = None
        self.processor = None
        self.processing_thread = None
        self._processing_result = None
        self._processing_error_message = None
        self.pending_files = []
        self.selected_files = []
        self.current_file_set = []
        self.current_mode = "idle"  # idle | batch | sequence | watch
        self.sequence_file_path = None
        self.sequence_digits = 0
        self.sequence_index = None
        self.file_history_records = []
        self.requested_input_files = 0
        self.requested_file_sets = 0
        self.completed_file_sets = 0
        
        # Setup logging
        self._setup_logging()
        
        # Create UI
        self._create_ui()
        self.log_message.connect(self._append_log)
        
        # Timer to check for new files
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_for_files)
        
        # Load saved settings
        self._load_settings()
        self._append_log(
            f"Runtime: v{__version__} | gui={Path(__file__).resolve()}"
        )

    def _set_window_icon(self):
        """Load the packaged application icon when available."""
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        
    def _setup_logging(self):
        """Setup logging to GUI console."""
        self.log_handler = logging.Handler()
        self.log_handler.setLevel(logging.INFO)
        
        # Will connect to text widget after UI creation
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                     datefmt='%H:%M:%S')
        self.log_handler.setFormatter(formatter)
        self.log_handler.emit = lambda record: self.log_message.emit(
            self.log_handler.format(record)
        )

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(self.log_handler)
        
    def _create_ui(self):
        """Create the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(right_layout, 4)

        # Top header with version
        # header_label = QLabel(f"Dioptas Batch Processor v{__version__}")
        # header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        # main_layout.addWidget(header_label)
        
        # Mode selector tabs
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        
        # Batch Mode Tab
        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)
        self._create_batch_mode_ui(batch_layout)
        self.mode_tabs.addTab(batch_tab, "Batch Mode (Manual)")

        # Sequence Mode Tab
        sequence_tab = QWidget()
        sequence_layout = QVBoxLayout(sequence_tab)
        self._create_sequence_mode_ui(sequence_layout)
        self.mode_tabs.addTab(sequence_tab, "Sequence Mode (Manual)")

        # Watch Mode Tab
        watch_tab = QWidget()
        watch_layout = QVBoxLayout(watch_tab)
        self._create_watch_mode_ui(watch_layout)
        self.mode_tabs.addTab(watch_tab, "Watch Mode (Auto)")
        
        left_layout.addWidget(self.mode_tabs)
        left_layout.addStretch(1)
        
        # Shared configuration section
        config_group = QGroupBox("Processing Configuration")
        config_layout = QVBoxLayout()
        
        # Output directory
        output_label = QLabel("Output Directory:")
        output_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        config_layout.addWidget(output_label)
        output_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        output_layout.addWidget(self.output_dir_edit)
        self.output_dir_btn = QPushButton("Browse...")
        self.output_dir_btn.clicked.connect(self._browse_output_dir)
        output_layout.addWidget(self.output_dir_btn)
        config_layout.addLayout(output_layout)
        
        # Calibration file
        cal_label = QLabel("Calibration File (.poni):")
        cal_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        config_layout.addWidget(cal_label)
        cal_layout = QHBoxLayout()
        self.cal_file_edit = QLineEdit()
        cal_layout.addWidget(self.cal_file_edit)
        self.cal_file_btn = QPushButton("Browse...")
        self.cal_file_btn.clicked.connect(self._browse_cal_file)
        cal_layout.addWidget(self.cal_file_btn)
        config_layout.addLayout(cal_layout)
        
        # Mask file (optional)
        mask_label = QLabel("Mask File (optional):")
        mask_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        config_layout.addWidget(mask_label)
        mask_layout = QHBoxLayout()
        self.mask_file_edit = QLineEdit()
        mask_layout.addWidget(self.mask_file_edit)
        self.mask_file_btn = QPushButton("Browse...")
        self.mask_file_btn.clicked.connect(self._browse_mask_file)
        mask_layout.addWidget(self.mask_file_btn)
        config_layout.addLayout(mask_layout)
        
        config_group.setLayout(config_layout)
        left_layout.addWidget(config_group)
        left_layout.addStretch(1)
        
        # Processing Options
        options_group = QGroupBox("Processing Options")
        options_layout = QVBoxLayout()
        
        # Integration controls
        integration_grid = QGridLayout()
        integration_grid.setHorizontalSpacing(12)
        integration_grid.setVerticalSpacing(8)

        integration_label = QLabel("Integration Points (1D):")
        integration_grid.addWidget(integration_label, 0, 0)
        self.integration_points_edit = QLineEdit("Auto")
        self.integration_points_edit.setReadOnly(True)
        self.integration_points_edit.setFixedWidth(110)
        self.integration_points_edit.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.integration_points_edit.setToolTip(
            "Updated automatically from the loaded image using Dioptas."
        )
        integration_grid.addWidget(self.integration_points_edit, 0, 1)

        azimuth_label = QLabel("Azimuth Bins (2D):")
        integration_grid.addWidget(azimuth_label, 1, 0)
        self.azimuth_points_edit = QLineEdit(str(FIXED_AZIMUTH_BINS))
        self.azimuth_points_edit.setReadOnly(True)
        self.azimuth_points_edit.setFixedWidth(110)
        self.azimuth_points_edit.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.azimuth_points_edit.setToolTip("Fixed at 360 bins.")
        integration_grid.addWidget(self.azimuth_points_edit, 1, 1)
        integration_grid.setColumnStretch(2, 1)
        options_layout.addLayout(integration_grid)
        
        checkbox_grid = QGridLayout()
        checkbox_grid.setHorizontalSpacing(24)
        checkbox_grid.setVerticalSpacing(8)

        self.export_chi_cb = QCheckBox("Export CHI files")
        self.export_chi_cb.setChecked(True)
        checkbox_grid.addWidget(self.export_chi_cb, 0, 0)

        self.export_xy_cb = QCheckBox("Export XY files")
        self.export_xy_cb.setChecked(False)
        checkbox_grid.addWidget(self.export_xy_cb, 0, 1)

        self.export_dat_cb = QCheckBox("Export DAT files")
        self.export_dat_cb.setChecked(False)
        checkbox_grid.addWidget(self.export_dat_cb, 1, 0)
        
        self.export_npy_cb = QCheckBox("Export NPY files")
        self.export_npy_cb.setChecked(True)
        checkbox_grid.addWidget(self.export_npy_cb, 1, 1)

        self.apply_mask_to_chi_cb = QCheckBox("Apply mask to CHI")
        self.apply_mask_to_chi_cb.setChecked(True)
        checkbox_grid.addWidget(self.apply_mask_to_chi_cb, 2, 0)

        self.apply_mask_to_cake_cb = QCheckBox("Apply mask to cake")
        self.apply_mask_to_cake_cb.setChecked(False)
        checkbox_grid.addWidget(self.apply_mask_to_cake_cb, 2, 1)
        options_layout.addLayout(checkbox_grid)

        overwrite_layout = QHBoxLayout()
        self.overwrite_cb = QCheckBox("Overwrite existing files")
        self.overwrite_cb.setChecked(False)
        overwrite_layout.addWidget(self.overwrite_cb)
        overwrite_layout.addStretch()
        options_layout.addLayout(overwrite_layout)
        
        options_group.setLayout(options_layout)
        left_layout.addWidget(options_group)
        left_layout.addStretch(1)
        
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
        left_layout.addWidget(progress_group)
        left_layout.addStretch(1)

        file_list_group = QGroupBox("File List")
        file_list_layout = QVBoxLayout()

        self.file_list_table = QTableWidget(0, 2)
        self.file_list_table.setHorizontalHeaderLabels(["File", "Processed"])
        self.file_list_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_list_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_list_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list_table.verticalHeader().setVisible(False)
        self.file_list_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list_table.verticalHeader().setDefaultSectionSize(28)
        self.file_list_table.setMinimumHeight(280)
        self.file_list_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.file_list_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        file_list_layout.addWidget(self.file_list_table)

        file_list_legend = QLabel(
            '<span style="color: #cc0000; font-weight: 600;">Red</span>: overwritten files | '
            '<span style="color: #008000; font-weight: 600;">Green</span>: skipped because output files already exist | '
            "White: processed files | "
            "White italic: pending files"
        )
        file_list_legend.setTextFormat(Qt.TextFormat.RichText)
        file_list_legend.setWordWrap(True)
        file_list_legend.setStyleSheet(
            "color: #d9d9d9; font-size: 11px; padding-top: 4px;"
        )
        file_list_layout.addWidget(file_list_legend)

        file_list_group.setLayout(file_list_layout)
        right_layout.addWidget(file_list_group, 3)
        
        # Log console
        log_group = QGroupBox("Processing Log")
        log_layout = QVBoxLayout()
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(150)
        self.log_console.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.log_console.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.log_console.setStyleSheet(
            "background-color: #f5f5f5; color: #000000; font-family: Menlo, Monaco, 'Courier New';"
        )
        log_layout.addWidget(self.log_console)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_console.clear)
        log_layout.addWidget(clear_btn)
        
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group, 2)
        
    def _create_watch_mode_ui(self, layout):
        """Create UI for watch mode."""
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
        self.watch_toggle_btn = QPushButton("Start Watching")
        self.watch_toggle_btn.setCheckable(True)
        self.watch_toggle_btn.clicked.connect(self._toggle_watching)
        self.watch_toggle_btn.setStyleSheet(self._watch_toggle_stylesheet())
        control_layout.addWidget(self.watch_toggle_btn)
        
        layout.addLayout(control_layout)
        layout.addStretch()

    def _watch_toggle_stylesheet(self):
        """Return stylesheet for the watch toggle button."""
        return (
            "QPushButton {"
            " background-color: #4CAF50;"
            " border: 2px solid #388E3C;"
            " border-radius: 4px;"
            " color: white;"
            " font-weight: bold;"
            " padding: 8px 14px;"
            "}"
            "QPushButton:pressed {"
            " padding-top: 9px;"
            " padding-left: 15px;"
            "}"
            "QPushButton:checked {"
            " background-color: #f44336;"
            " border: 2px inset #B71C1C;"
            " padding-top: 9px;"
            " padding-left: 15px;"
            "}"
            "QPushButton:checked:pressed {"
            " background-color: #d73a2f;"
            "}"
        )

    def _set_watch_toggle_state(self, is_watching):
        """Update toggle button label and checked state."""
        self.watch_toggle_btn.blockSignals(True)
        self.watch_toggle_btn.setChecked(is_watching)
        self.watch_toggle_btn.setText("Stop Watching" if is_watching else "Start Watching")
        self.watch_toggle_btn.blockSignals(False)

    def _toggle_watching(self, checked):
        """Toggle folder watching from the single watch button."""
        if checked:
            self._start_watching()
        else:
            self._stop_watching()

    def _create_sequence_mode_ui(self, layout):
        """Create UI for manually stepping through a numbered file sequence."""
        select_layout = QHBoxLayout()
        select_layout.setSpacing(12)
        self.sequence_select_btn = QPushButton("Select File ...")
        self.sequence_select_btn.clicked.connect(self._select_sequence_file)
        self.sequence_select_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        self.sequence_process_btn = QPushButton("Process Current File")
        self.sequence_process_btn.clicked.connect(self._process_current_sequence_file)
        self.sequence_process_btn.hide()
        select_layout.addWidget(self.sequence_select_btn)
        self.sequence_prev_btn = QPushButton("<")
        self.sequence_prev_btn.clicked.connect(lambda: self._step_sequence(-1))
        self.sequence_prev_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; }"
        )
        self.sequence_prev_btn.setEnabled(False)
        select_layout.addWidget(self.sequence_prev_btn)

        self.sequence_next_btn = QPushButton(">")
        self.sequence_next_btn.clicked.connect(lambda: self._step_sequence(1))
        self.sequence_next_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; }"
        )
        self.sequence_next_btn.setEnabled(False)
        select_layout.addWidget(self.sequence_next_btn)
        sequence_button_height = max(
            self.sequence_select_btn.sizeHint().height(),
            self.sequence_prev_btn.sizeHint().height(),
            self.sequence_next_btn.sizeHint().height(),
            46,
        )
        self.sequence_select_btn.setFixedHeight(sequence_button_height)
        self.sequence_prev_btn.setFixedHeight(sequence_button_height)
        self.sequence_next_btn.setFixedHeight(sequence_button_height)

        self.sequence_nav_name_rb = QRadioButton("Name")
        self.sequence_nav_name_rb.setChecked(True)
        select_layout.addWidget(self.sequence_nav_name_rb)
        self.sequence_nav_time_rb = QRadioButton("Time")
        select_layout.addWidget(self.sequence_nav_time_rb)
        select_layout.addStretch()
        layout.addLayout(select_layout)
        layout.addStretch()
        
    def _create_batch_mode_ui(self, layout):
        """Create UI for batch mode."""
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(8)

        # File selection
        file_select_layout = QHBoxLayout()
        self.select_files_btn = QPushButton("Select Files...")
        self.select_files_btn.clicked.connect(self._select_files)
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self._clear_selection)

        self.select_files_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        self.select_files_btn.setFixedHeight(self.clear_selection_btn.sizeHint().height())

        file_select_layout.addWidget(self.select_files_btn)
        file_select_layout.addWidget(self.clear_selection_btn)
        self.process_batch_btn = QPushButton("Process Selected Files")
        self.process_batch_btn.clicked.connect(self._process_batch)
        self.process_batch_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; }"
        )
        self.process_batch_btn.setEnabled(False)
        common_button_height = max(
            self.select_files_btn.sizeHint().height(),
            self.clear_selection_btn.sizeHint().height(),
            self.process_batch_btn.sizeHint().height(),
        )
        self.select_files_btn.setFixedHeight(common_button_height)
        self.clear_selection_btn.setFixedHeight(common_button_height)
        self.process_batch_btn.setFixedHeight(common_button_height)
        file_select_layout.addWidget(self.process_batch_btn)
        
        file_select_layout.addStretch()
        layout.addLayout(file_select_layout)
        
    def _append_log(self, message):
        """Append message to log console."""
        if "OVERWRITE:" in message:
            self._append_colored_log(message, "#cc0000")
            return
        if "SKIPPED:" in message:
            self._append_colored_log(message, "#008000")
            return
        self.log_console.append(message)
        self.log_console.verticalScrollBar().setValue(
            self.log_console.verticalScrollBar().maximum()
        )

    def _append_colored_log(self, message, color):
        """Append a single colored log line to the console."""
        self.log_console.append(
            f'<span style="color: {escape(color, quote=True)};">{escape(message)}</span>'
        )
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
            self._set_pending_batch_files(file_paths)
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
        self._clear_pending_batch_files()
        self.process_batch_btn.setEnabled(False)
        self._append_log("File selection cleared")

    def _select_sequence_file(self):
        """Select one file that represents a manually stepped numbered sequence."""
        settings = QSettings("Dioptas", "BatchProcessor")
        last_file_dir = settings.value("last_file_dir", "")

        if not last_file_dir and self.output_dir_edit.text():
            last_file_dir = self.output_dir_edit.text()

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sequence File",
            last_file_dir,
            "HDF5 Files (*.h5 *.nxs);;All Files (*)"
        )
        if not file_path:
            return

        if not self._set_sequence_file(file_path):
            QMessageBox.warning(
                self,
                "Sequence Error",
                "The selected file name must contain a sequence number, either at the end "
                "or immediately after 'map'."
            )
            return

        file_directory = str(Path(file_path).parent)
        self.output_dir_edit.setText(file_directory)
        settings.setValue("last_file_dir", file_directory)
        self._save_settings()
        self._append_log(f"Selected sequence file: {Path(file_path).name}")
        self._add_pending_files([file_path])
        self._process_current_sequence_file()

    def _set_sequence_file(self, file_path: str) -> bool:
        """Store sequence metadata for a numbered file path."""
        path = Path(file_path)
        match = re.search(r"map[_-]*(\d+)", path.stem, re.IGNORECASE)
        if not match:
            match = re.search(r"(\d+)$", path.stem)
        if not match:
            return False

        self.sequence_file_path = path
        self.sequence_digits = len(match.group(1))
        self.sequence_index = int(match.group(1))
        self._update_sequence_controls()
        return True

    def _update_sequence_controls(self):
        """Refresh sequence UI from the current file selection."""
        if self.sequence_file_path is None or self.sequence_index is None:
            self.sequence_prev_btn.setEnabled(False)
            self.sequence_next_btn.setEnabled(False)
            return

        is_busy = self.processing_thread is not None
        self.sequence_prev_btn.setEnabled(not is_busy)
        self.sequence_next_btn.setEnabled(not is_busy)

    def _sequence_navigation_mode(self) -> str:
        """Return the active sequence navigation mode."""
        return "time" if self.sequence_nav_time_rb.isChecked() else "name"

    def _sequence_sort_key(self, path: Path):
        """Return a name-sorting key that treats map_2 before map_10."""
        stem_lower = path.stem.lower()
        map_match = re.search(r"^(.*?map[_-]?)(\d+)(.*)$", stem_lower)
        if map_match:
            return (
                map_match.group(1),
                int(map_match.group(2)),
                map_match.group(3),
                path.suffix.lower(),
                path.name.lower(),
            )

        tail_match = re.search(r"^(.*?)(\d+)$", stem_lower)
        if tail_match:
            return (
                tail_match.group(1),
                int(tail_match.group(2)),
                "",
                path.suffix.lower(),
                path.name.lower(),
            )

        return (stem_lower, float("inf"), "", path.suffix.lower(), path.name.lower())

    def _sequence_candidate_files(self) -> list[Path]:
        """Return candidate sequence files from the current directory."""
        if self.sequence_file_path is None:
            return []

        suffixes = {".h5", ".nxs"}
        candidates = [
            path for path in self.sequence_file_path.parent.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        ]

        if self._sequence_navigation_mode() == "time":
            return sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name))
        return sorted(candidates, key=self._sequence_sort_key)

    def _adjacent_sequence_path(self, delta: int) -> Path | None:
        """Return the next or previous existing file according to the selected navigation mode."""
        candidates = self._sequence_candidate_files()
        if not candidates or self.sequence_file_path not in candidates:
            return None

        current_idx = candidates.index(self.sequence_file_path)
        target_idx = current_idx + delta
        if target_idx < 0 or target_idx >= len(candidates):
            return None
        return candidates[target_idx]

    def _step_sequence(self, delta: int):
        """Move to the previous or next file and process it."""
        if self.sequence_file_path is None or self.sequence_index is None:
            return
        if self.processing_thread is not None:
            return

        next_path = self._adjacent_sequence_path(delta)
        if next_path is None:
            direction = "next" if delta > 0 else "previous"
            QMessageBox.warning(
                self,
                "Sequence Error",
                f"No {direction} file was found for navigation by {self._sequence_navigation_mode()}."
            )
            return

        self._set_sequence_file(str(next_path))
        self._append_log(f"Moved to sequence file: {next_path.name}")
        self._add_pending_files([str(next_path)])
        self._process_current_sequence_file()

    def _process_current_sequence_file(self):
        """Process the currently selected sequence file."""
        if self.sequence_file_path is None:
            QMessageBox.warning(self, "No File", "Please select a sequence file to process.")
            return
        if self.processing_thread is not None:
            return
        if not self._validate_config(check_watch_dir=False):
            return

        self._save_settings()

        try:
            mask_file = self.mask_file_edit.text() if self.mask_file_edit.text() else None
            self.processor = BatchProcessor(
                calibration_file=self.cal_file_edit.text(),
                output_directory=self.output_dir_edit.text(),
                mask_file=mask_file,
                num_points=1,
                cake_azimuth_points=FIXED_AZIMUTH_BINS,
                overwrite=self.overwrite_cb.isChecked()
            )
            self._append_log(
                "Requested integration settings: "
                "radial=auto, "
                f"azimuth={FIXED_AZIMUTH_BINS}, "
                f"overwrite={self.overwrite_cb.isChecked()}"
            )
            self._append_log(f"=== Processing sequence file: {self.sequence_file_path.name} ===")

            self.current_mode = "sequence"
            self.requested_input_files = 1
            self.requested_file_sets = 1
            self.completed_file_sets = 0
            self.pending_files = [str(self.sequence_file_path)]
            self._update_sequence_controls()
            self._update_stats_label()
            self._process_next_batch()
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to process sequence file:\n{str(e)}\n\nSee log for details."
            )
            logging.error(f"Sequence processing error: {e}")
            logging.error(f"Traceback:\n{error_details}")
            self._append_log(f"ERROR: {str(e)}")
            self._update_sequence_controls()
        
    def _load_settings(self):
        """Load saved settings."""
        settings = QSettings("Dioptas", "BatchProcessor")
        self.output_dir_edit.setText(settings.value("output_dir", ""))
        self.cal_file_edit.setText(settings.value("cal_file", ""))
        self.mask_file_edit.setText(settings.value("mask_file", ""))
        self.watch_dir_edit.setText(settings.value("watch_dir", ""))
        self.export_xy_cb.setChecked(settings.value("export_xy", False, type=bool))
        self.export_dat_cb.setChecked(settings.value("export_dat", False, type=bool))
        self.apply_mask_to_chi_cb.setChecked(settings.value("apply_mask_to_chi", True, type=bool))
        self.apply_mask_to_cake_cb.setChecked(settings.value("apply_mask_to_cake", False, type=bool))
        
    def _save_settings(self):
        """Save current settings."""
        settings = QSettings("Dioptas", "BatchProcessor")
        settings.setValue("output_dir", self.output_dir_edit.text())
        settings.setValue("cal_file", self.cal_file_edit.text())
        settings.setValue("mask_file", self.mask_file_edit.text())
        settings.setValue("watch_dir", self.watch_dir_edit.text())
        settings.setValue("export_xy", self.export_xy_cb.isChecked())
        settings.setValue("export_dat", self.export_dat_cb.isChecked())
        settings.setValue("apply_mask_to_chi", self.apply_mask_to_chi_cb.isChecked())
        settings.setValue("apply_mask_to_cake", self.apply_mask_to_cake_cb.isChecked())

    def _selected_1d_output_paths(self, base_name: str):
        """Return selected 1D output paths for a base file name."""
        output_dir = Path(self.output_dir_edit.text())
        selected_paths = []
        if self.export_chi_cb.isChecked():
            selected_paths.append(output_dir / f"{base_name}.chi")
        if self.export_xy_cb.isChecked():
            selected_paths.append(output_dir / f"{base_name}.xy")
        if self.export_dat_cb.isChecked():
            selected_paths.append(output_dir / f"{base_name}.dat")
        return selected_paths
    
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

        self._save_settings()
            
        try:
            # Initialize processor
            mask_file = self.mask_file_edit.text() if self.mask_file_edit.text() else None
            self.processor = BatchProcessor(
                calibration_file=self.cal_file_edit.text(),
                output_directory=self.output_dir_edit.text(),
                mask_file=mask_file,
                num_points=1,
                cake_azimuth_points=FIXED_AZIMUTH_BINS,
                overwrite=self.overwrite_cb.isChecked()
            )
            self._append_log(
                "Requested integration settings: "
                "radial=auto, "
                f"azimuth={FIXED_AZIMUTH_BINS}, "
                f"overwrite={self.overwrite_cb.isChecked()}"
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
            self._set_watch_toggle_state(False)
            return

        self._save_settings()
            
        try:
            # Initialize processor
            mask_file = self.mask_file_edit.text() if self.mask_file_edit.text() else None
            self.processor = BatchProcessor(
                calibration_file=self.cal_file_edit.text(),
                output_directory=self.output_dir_edit.text(),
                mask_file=mask_file,
                num_points=1,
                cake_azimuth_points=FIXED_AZIMUTH_BINS,
                overwrite=self.overwrite_cb.isChecked()
            )
            self._append_log(
                "Requested integration settings: "
                "radial=auto, "
                f"azimuth={FIXED_AZIMUTH_BINS}, "
                f"overwrite={self.overwrite_cb.isChecked()}"
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
                for file_path in existing_files:
                    base_name = Path(file_path).stem
                    required_1d_paths = self._selected_1d_output_paths(base_name)
                    if not required_1d_paths or not all(path.exists() for path in required_1d_paths):
                        unprocessed_files.append(file_path)
                
                if unprocessed_files:
                    self._append_log(f"Found {len(unprocessed_files)} existing unprocessed files")
                    self.pending_files.extend(unprocessed_files)
                    self._add_pending_files(unprocessed_files)
                    # Start processing immediately
                    self._process_next_batch()
            
            # Start timer to check for files
            self.check_timer.start(1000)  # Check every second
            
            # Update UI
            self._set_watch_toggle_state(True)
            self.status_label.setText("Status: Watching for files...")
            self.status_label.setStyleSheet("color: green;")
            
            self._append_log("=== Auto-processing started ===")
            
        except Exception as e:
            self._set_watch_toggle_state(False)
            QMessageBox.critical(self, "Error", f"Failed to start: {str(e)}")
            logging.error(f"Failed to start: {e}")
            
    def _stop_watching(self):
        """Stop file watching."""
        if self.file_watcher:
            self.file_watcher.stop()
            self.file_watcher = None
            
        self.check_timer.stop()
        
        # Update UI
        self._set_watch_toggle_state(False)
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
            self._add_pending_files(completed_files)
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
            self.export_xy_cb.isChecked(),
            self.export_dat_cb.isChecked(),
            self.export_npy_cb.isChecked(),
            self.apply_mask_to_chi_cb.isChecked(),
            self.apply_mask_to_cake_cb.isChecked(),
        )
        self.processing_thread.progress.connect(self._update_progress)
        self.processing_thread.result_ready.connect(self._store_processing_result)
        self.processing_thread.error.connect(self._store_processing_error)
        self.processing_thread.finished.connect(self._processing_thread_finished)
        self.processing_thread.integration_points_estimated.connect(
            self._update_integration_points_spinbox
        )
        if self.current_mode == "sequence":
            self._update_sequence_controls()
        self.processing_thread.start()
        self._append_log("-" * 80)
        self._append_log(f"Starting file set: {Path(file_set[0]).stem}")
        if self.current_mode == "batch":
            self.progress_bar.setMaximum(1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%v/%m images")
        else:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
        self.status_label.setText(f"Status: Processing {Path(file_set[0]).stem}...")
        self._update_stats_label()
        
    def _update_progress(self, current, total, message):
        """Update progress bar."""
        if self.current_mode == "batch" and self.requested_file_sets:
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(current)
            current_set_idx = self.completed_file_sets + 1
            self.status_label.setText(
                f"Status: File set {current_set_idx}/{self.requested_file_sets} | {message}"
            )
        elif self.current_mode == "sequence":
            self.status_label.setText(
                f"Status: Sequence {Path(self.current_file_set[0]).stem} | {message}"
            )
        else:
            self.status_label.setText(f"Status: {message}")

    def _update_integration_points_spinbox(self, num_points):
        """Reflect Dioptas' current radial-bin estimate in the GUI."""
        num_points = int(num_points)
        if self.integration_points_edit.text() == str(num_points):
            return
        self.integration_points_edit.setText(str(num_points))

    def _record_file_history_status(self, file_paths, status):
        """Mark source files with their final status in the side-panel history."""
        completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for file_path in file_paths:
            resolved_path = str(Path(file_path).resolve())
            updated = False
            for record in self.file_history_records:
                if record["path"] == resolved_path and record["status"] == "pending":
                    record["status"] = status
                    record["completed_at"] = completed_at
                    updated = True
                    break
            if not updated:
                self.file_history_records.append(
                    {
                        "path": resolved_path,
                        "status": status,
                        "completed_at": completed_at,
                    }
                )
        self._render_file_history()

    def _record_processed_files(self, file_paths):
        """Mark completed source files in the side-panel history."""
        self._record_file_history_status(file_paths, "processed")

    def _record_skipped_files(self, file_paths):
        """Mark skipped source files in the side-panel history."""
        self._record_file_history_status(file_paths, "skipped")

    def _record_overwritten_files(self, file_paths):
        """Mark overwritten source files in the side-panel history."""
        self._record_file_history_status(file_paths, "overwritten")

    def _add_pending_files(self, file_paths):
        """Append pending source files to the side-panel history."""
        for file_path in file_paths:
            resolved_path = str(Path(file_path).resolve())
            self.file_history_records.append(
                {
                    "path": resolved_path,
                    "status": "pending",
                    "completed_at": "",
                }
            )
        self._render_file_history()

    def _set_pending_batch_files(self, file_paths):
        """Show newly selected batch files immediately in italic without timestamps."""
        self._clear_pending_batch_files()
        self._add_pending_files(file_paths)

    def _clear_pending_batch_files(self):
        """Remove any still-pending batch selections from the side-panel history."""
        self.file_history_records = [
            record for record in self.file_history_records
            if record["status"] != "pending"
        ]
        self._render_file_history()

    def _remove_pending_files(self, file_paths):
        """Remove specific pending file entries from the side-panel history."""
        paths_to_remove = {str(Path(file_path).resolve()) for file_path in file_paths}
        self.file_history_records = [
            record for record in self.file_history_records
            if not (record["status"] == "pending" and record["path"] in paths_to_remove)
        ]
        self._render_file_history()

    def _render_file_history(self):
        """Render the side-panel file history as a two-column table."""
        self.file_list_table.setRowCount(len(self.file_history_records))
        for row, record in enumerate(self.file_history_records):
            path_label = QLabel()
            path_label.setTextFormat(Qt.TextFormat.PlainText)
            path_label.setToolTip(record["path"])
            path_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            path_label.setIndent(4)
            label_font = path_label.font()
            if record["status"] == "pending":
                label_font.setItalic(True)
            path_label.setFont(label_font)
            if record["status"] == "skipped":
                path_label.setStyleSheet("color: #008000;")
            elif record["status"] == "overwritten":
                path_label.setStyleSheet("color: #cc0000;")
            available_width = max(
                80,
                self.file_list_table.columnWidth(0) - 16,
            )
            elided_text = QFontMetrics(label_font).elidedText(
                record["path"],
                Qt.TextElideMode.ElideLeft,
                available_width,
            )
            path_label.setText(elided_text)

            processed_item = QTableWidgetItem(record["completed_at"])
            if record["status"] == "skipped":
                processed_item.setForeground(Qt.GlobalColor.darkGreen)
            elif record["status"] == "overwritten":
                processed_item.setForeground(Qt.GlobalColor.red)
            self.file_list_table.setCellWidget(row, 0, path_label)
            self.file_list_table.setItem(row, 1, processed_item)

        self.file_list_table.scrollToBottom()
        
    def _processing_finished(self, stats):
        """Handle processing completion."""
        self.completed_file_sets += 1
        if self.current_mode == "batch":
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
        else:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("%p%")
        
        self._append_log(
            f"Completed: {stats['processed']}/{stats['total_images']} images "
            f"(skipped: {stats.get('skipped', 0)})"
        )
        skipped_all = (
            stats.get("processed", 0) > 0
            and stats.get("processed", 0) == stats.get("skipped", 0)
            and stats.get("failed", 0) == 0
        )
        if skipped_all:
            self._record_skipped_files(self.current_file_set)
            if self.current_mode in {"batch", "sequence"}:
                current_name = Path(self.current_file_set[0]).stem if self.current_file_set else "-"
                self._append_log(
                    "SKIPPED: existing outputs for "
                    f"{current_name}: overwrite is disabled."
                )
        elif stats.get("overwritten", 0) > 0:
            self._record_overwritten_files(self.current_file_set)
        elif stats.get("processed", 0) > 0:
            self._record_processed_files(self.current_file_set)
        
        # Update stats
        self._update_stats_label(stats)
        
        # Process next batch if available
        if self.pending_files:
            self._process_next_batch()
        else:
            # Check which mode we're in
            if self.file_watcher and self.file_watcher.is_running:
                self.status_label.setText("Status: Watching for files...")
            elif self.current_mode == "sequence":
                self.status_label.setText("Status: Sequence file processed")
                self._update_sequence_controls()
            else:
                self.status_label.setText("Status: All files processed")
                # Re-enable batch mode controls
                self.process_batch_btn.setEnabled(len(self.selected_files) > 0)
                self.select_files_btn.setEnabled(True)
            
    def _processing_error(self, error_msg):
        """Handle processing error."""
        if self.current_mode != "batch":
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
        else:
            self.progress_bar.setValue(0)
        self._append_log(f"ERROR: {error_msg}")
        self.status_label.setText("Status: Error occurred")
        if self.current_mode == "sequence":
            self._update_sequence_controls()
        else:
            self.process_batch_btn.setEnabled(len(self.selected_files) > 0)
            self.select_files_btn.setEnabled(True)
        self._update_stats_label()

    def _store_processing_result(self, stats):
        """Store worker results until Qt reports the thread has fully stopped."""
        self._processing_result = stats

    def _store_processing_error(self, error_msg):
        """Store worker errors until Qt reports the thread has fully stopped."""
        self._processing_error_message = error_msg

    def _processing_thread_finished(self):
        """Finalize thread cleanup only after the underlying QThread has exited."""
        thread = self.processing_thread
        result = self._processing_result
        error_msg = self._processing_error_message

        self.processing_thread = None
        self._processing_result = None
        self._processing_error_message = None

        if thread is not None:
            thread.deleteLater()

        if error_msg is not None:
            self._processing_error(error_msg)
            return

        if result is not None:
            self._processing_finished(result)
            return

        self._append_log("ERROR: Processing thread exited without returning a result.")
        self.status_label.setText("Status: Error occurred")
        self.process_batch_btn.setEnabled(len(self.selected_files) > 0)
        self.select_files_btn.setEnabled(True)
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

        if self.current_mode == "sequence":
            current_file = self.sequence_file_path.name if self.sequence_file_path else "-"
            if last_stats:
                self.stats_label.setText(
                    f"Sequence file: {current_file} | "
                    f"Last batch: {last_stats.get('processed', 0)}/{last_stats.get('total_images', 0)} images"
                )
            else:
                self.stats_label.setText(f"Sequence file: {current_file} | Pending files: {pending_count}")
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
        if self.processing_thread is not None:
            self._append_log("Waiting for active processing thread to finish before closing...")
            self.processing_thread.wait()
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    
    window = DioptasBatchGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
