#!/usr/bin/env python
"""
File Watcher Module for Dioptas Batch Processing
Monitors directories for new Lambda detector files and queues them for processing.
"""

import os
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from queue import Queue
import re
import h5py

logger = logging.getLogger(__name__)


class LambdaFileHandler(FileSystemEventHandler):
    """
    Handler for Lambda detector file events.
    Detects new .nxs files and adds them to processing queue.
    """
    
    def __init__(self, file_queue: Queue, file_pattern=r'.*\.nxs$', stable_seconds: float = 10.0):
        super().__init__()
        self.file_queue = file_queue
        self.file_pattern = re.compile(file_pattern)
        self.processed_files = set()
        self.pending_files = {}  # Track files being written
        self.stable_seconds = float(stable_seconds)
        self.last_activity_time = time.time()

    def _mark_activity(self, timestamp: float | None = None):
        """Record the most recent file activity seen by the watcher."""
        self.last_activity_time = time.time() if timestamp is None else float(timestamp)

    def _track_pending_file(self, file_path: str):
        """Start or refresh tracking for a file that may still be growing."""
        now = time.time()
        self._mark_activity(now)
        try:
            stat = Path(file_path).stat()
            size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size = None
            mtime = None

        tracked = self.pending_files.get(file_path)
        if tracked is None:
            self.pending_files[file_path] = {
                "last_event": now,
                "last_size": size,
                "last_mtime": mtime,
                "stable_since": None,
            }
            return

        tracked["last_event"] = now
        tracked["last_size"] = size
        tracked["last_mtime"] = mtime
        tracked["stable_since"] = None

    def _file_contents_look_complete(self, file_path: str) -> bool:
        """Return True once the file can be opened as a valid HDF5/Nexus file."""
        try:
            with h5py.File(file_path, "r") as handle:
                handle.visit(lambda _: None)
            return True
        except (OSError, IOError, RuntimeError, ValueError) as exc:
            logger.info(f"File not yet ready for HDF5 access: {file_path} ({exc})")
            return False
        
    def on_created(self, event):
        """Called when a new file is created."""
        if event.is_directory:
            return
            
        file_path = event.src_path
        
        # Check if file matches pattern
        if not self.file_pattern.match(file_path):
            return
            
        logger.info(f"Detected new file: {file_path}")
        self._track_pending_file(file_path)
        
    def on_modified(self, event):
        """Called when a file is modified (during writing)."""
        if event.is_directory:
            return
            
        file_path = event.src_path
        
        if self.file_pattern.match(file_path):
            self._track_pending_file(file_path)

    def on_moved(self, event):
        """Called when a file is renamed into place."""
        if event.is_directory:
            return

        file_path = event.dest_path
        if self.file_pattern.match(file_path):
            logger.info(f"Detected moved file: {file_path}")
            self._track_pending_file(file_path)
            
    def check_complete_files(self):
        """
        Check if pending files have finished writing.
        Files are considered complete once their size and mtime have remained
        unchanged for a sustained interval and the HDF5 container can be opened.
        """
        current_time = time.time()
        completed_files = []

        for file_path, tracked in list(self.pending_files.items()):
            if file_path in self.processed_files:
                del self.pending_files[file_path]
                continue

            if not os.path.exists(file_path):
                continue

            try:
                stat = Path(file_path).stat()
            except OSError as exc:
                logger.info(f"Could not stat pending file yet: {file_path} ({exc})")
                continue

            size = stat.st_size
            mtime = stat.st_mtime

            if size != tracked["last_size"] or mtime != tracked["last_mtime"]:
                self._mark_activity(current_time)
                tracked["last_size"] = size
                tracked["last_mtime"] = mtime
                tracked["last_event"] = current_time
                tracked["stable_since"] = None
                continue

            if tracked["stable_since"] is None:
                tracked["stable_since"] = current_time
                continue

            if current_time - tracked["stable_since"] < self.stable_seconds:
                continue

            if not self._file_contents_look_complete(file_path):
                tracked["stable_since"] = None
                continue

            completed_files.append(file_path)
            self.processed_files.add(file_path)
            del self.pending_files[file_path]
            logger.info(
                f"File ready for processing after {self.stable_seconds:.0f}s stable window: {file_path}"
            )
                 
        return completed_files


class FileWatcher:
    """
    Main file watcher class that monitors directory for new files.
    """
    
    def __init__(self, watch_directory: str, file_pattern=r'.*\.(nxs|h5)$', stable_seconds: float = 10.0):
        """
        Initialize file watcher.
        
        Args:
            watch_directory: Directory to monitor
            file_pattern: Regex pattern for files to watch (default: all .nxs or .h5 files)
            stable_seconds: Time that size/mtime must remain unchanged before read access
        """
        self.watch_directory = Path(watch_directory)
        self.file_queue = Queue()
        self.observer = Observer()
        self.event_handler = LambdaFileHandler(self.file_queue, file_pattern, stable_seconds)
        self.is_running = False
        
        # Verify directory exists
        if not self.watch_directory.exists():
            raise ValueError(f"Watch directory does not exist: {watch_directory}")
            
    def start(self):
        """Start monitoring the directory."""
        if self.is_running:
            logger.warning("File watcher already running")
            return
            
        logger.info(f"Starting file watcher on: {self.watch_directory}")
        self.observer.schedule(
            self.event_handler, 
            str(self.watch_directory), 
            recursive=True
        )
        self.observer.start()
        self.is_running = True
        
    def stop(self):
        """Stop monitoring the directory."""
        if not self.is_running:
            return
            
        logger.info("Stopping file watcher")
        self.observer.stop()
        self.observer.join(timeout=5)
        self.is_running = False
        
    def get_completed_files(self):
        """
        Get list of files that are ready for processing.
        
        Returns:
            List of file paths ready to be processed
        """
        return self.event_handler.check_complete_files()
        
    def get_pending_count(self):
        """Get number of files currently being written."""
        return len(self.event_handler.pending_files)

    def get_last_activity_time(self):
        """Return the latest watcher-observed file activity timestamp."""
        return self.event_handler.last_activity_time
        
    def clear_queue(self):
        """Clear the file queue."""
        while not self.file_queue.empty():
            self.file_queue.get()
            
    def get_queue_size(self):
        """Get current queue size."""
        return self.file_queue.qsize()


if __name__ == "__main__":
    # Test the file watcher
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    import sys
    if len(sys.argv) < 2:
        print("Usage: python file_watcher.py <directory_to_watch>")
        sys.exit(1)
        
    watch_dir = sys.argv[1]
    watcher = FileWatcher(watch_dir)
    
    try:
        watcher.start()
        print(f"Watching directory: {watch_dir}")
        print("Press Ctrl+C to stop")
        
        while True:
            time.sleep(1)
            completed = watcher.get_completed_files()
            for file_path in completed:
                print(f"Ready to process: {file_path}")
                
    except KeyboardInterrupt:
        print("\nStopping...")
        watcher.stop()
