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

logger = logging.getLogger(__name__)


class LambdaFileHandler(FileSystemEventHandler):
    """
    Handler for Lambda detector file events.
    Detects new .nxs files and adds them to processing queue.
    """
    
    def __init__(self, file_queue: Queue, file_pattern=r'.*\.nxs$'):
        super().__init__()
        self.file_queue = file_queue
        self.file_pattern = re.compile(file_pattern)
        self.processed_files = set()
        self.pending_files = {}  # Track files being written
        
    def on_created(self, event):
        """Called when a new file is created."""
        if event.is_directory:
            return
            
        file_path = event.src_path
        
        # Check if file matches pattern
        if not self.file_pattern.match(file_path):
            return
            
        logger.info(f"Detected new file: {file_path}")
        
        # Add to pending files (wait for write completion)
        self.pending_files[file_path] = time.time()
        
    def on_modified(self, event):
        """Called when a file is modified (during writing)."""
        if event.is_directory:
            return
            
        file_path = event.src_path
        
        # Update timestamp for pending files
        if file_path in self.pending_files:
            self.pending_files[file_path] = time.time()
            
    def check_complete_files(self):
        """
        Check if pending files have finished writing.
        Files are considered complete if no modifications for 2 seconds.
        """
        current_time = time.time()
        completed_files = []
        
        for file_path, last_modified in list(self.pending_files.items()):
            # File hasn't been modified for 2 seconds
            if current_time - last_modified > 2.0:
                if os.path.exists(file_path) and file_path not in self.processed_files:
                    # Verify file is readable
                    try:
                        with open(file_path, 'rb') as f:
                            f.read(1)  # Try to read first byte
                        completed_files.append(file_path)
                        self.processed_files.add(file_path)
                        logger.info(f"File ready for processing: {file_path}")
                    except (IOError, OSError) as e:
                        logger.warning(f"File not yet readable: {file_path}, {e}")
                        continue
                        
                del self.pending_files[file_path]
                
        return completed_files


class FileWatcher:
    """
    Main file watcher class that monitors directory for new files.
    """
    
    def __init__(self, watch_directory: str, file_pattern=r'.*\.(nxs|h5)$'):
        """
        Initialize file watcher.
        
        Args:
            watch_directory: Directory to monitor
            file_pattern: Regex pattern for files to watch (default: all .nxs or .h5 files)
        """
        self.watch_directory = Path(watch_directory)
        self.file_queue = Queue()
        self.observer = Observer()
        self.event_handler = LambdaFileHandler(self.file_queue, file_pattern)
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
