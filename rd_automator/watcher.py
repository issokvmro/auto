import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable

logger = logging.getLogger(__name__)

class NewFileHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None], debounce_seconds: int = 5):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._pending_files = {}

    def on_created(self, event):
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        logger.info(f"Detected new file: {path}")
        # Processing and stability check is now handed off to the orchestrator (callback)
        # to avoid blocking the watcher thread.
        self.callback(path)

class DirectoryWatcher:
    def __init__(self, watch_path: Path, callback: Callable[[Path], None]):
        self.watch_path = watch_path
        self.callback = callback
        self.observer = Observer()
        self.handler = NewFileHandler(callback)

    def start(self):
        logger.info(f"Starting watcher on {self.watch_path}")
        self.observer.schedule(self.handler, str(self.watch_path), recursive=False)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
