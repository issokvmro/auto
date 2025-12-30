import logging
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
from .config import settings
from .torrent_creator import create_torrent
from .rd_client import RealDebridClient
from .watcher import DirectoryWatcher
from .seeder import SeederManager
from .uploader import DropboxUploader

# Setup basic logging
# ... (logging setup is fine, assuming standard logging block is here or imported) ...
# Actually better to just replace the imports and the specific method logic.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("rd_automator.log")
    ]
)
logger = logging.getLogger("rd_automator")

class Orchestrator:
    def __init__(self):
        self.rd = RealDebridClient(token=settings.rd_api_token)
        self.seeder = SeederManager()
        self.active_items: Dict[str, Dict] = {} 
        self.lock = threading.Lock()
        self.running = True
        
        # Concurrency
        self.executor = None # Initialized in start()

    def _wait_for_file_stability(self, file_path: Path, debounce_seconds=2) -> bool:
        """
        Waits for a file to stop changing size.
        Returns True if stable, False if file disappeared.
        """
        initial_size = -1
        while True:
            try:
                current_size = file_path.stat().st_size
            except FileNotFoundError:
                return False

            if current_size == initial_size and current_size > 0:
                return True
            
            initial_size = current_size
            time.sleep(debounce_seconds)

    def process_new_file(self, file_path: Path):
        """
        Callback for new files.
        """
        if self.executor:
            self.executor.submit(self._process_file_task, file_path)
        else:
            logger.warning("Executor not started! processing sync.")
            self._process_file_task(file_path)

    def _process_file_task(self, file_path: Path):
        # 1. Wait for stability
        logger.info(f"Waiting for file stability: {file_path}")
        if not self._wait_for_file_stability(file_path):
            logger.error(f"File {file_path} disappeared or is invalid.")
            return

        logger.info(f"Processing item: {file_path} (Mode: {settings.upload_mode})")
        
        try:
            if settings.upload_mode == "hoster":
                self._process_hoster_mode(file_path)
            else:
                self._process_torrent_mode(file_path)
        except Exception as e:
            logger.error(f"Error in main process dispatch: {e}", exc_info=True)

    def _process_hoster_mode(self, file_path: Path):
        # 1. Upload to Dropbox
        url = DropboxUploader.upload_file(file_path)
        if not url:
            logger.error("Hoster upload failed. Aborting.")
            return

        # 2. Unrestrict on Real-Debrid
        logger.info(f"Unrestricting link: {url}")
        try:
            data = self.rd.unrestrict_link(url)
            logger.info(f"Unrestrict successful! Download ID: {data.get('id')}")
            
            # Save to log file
            download_link = data.get("download")
            if download_link:
                log_line = f"{file_path.name} - {download_link}\n"
                try:
                    with open("unrestricted_links.txt", "a", encoding="utf-8") as f:
                        f.write(log_line)
                    logger.info("Saved link to unrestricted_links.txt")
                except Exception as e:
                    logger.error(f"Failed to write to link log: {e}")

            # 3. Cleanup Dropbox
            logger.info("Cleaning up Dropbox to save space...")
            DropboxUploader.delete_file(file_path.name)

        except Exception as e:
            logger.error(f"Unrestrict failed: {e}")

    def _process_torrent_mode(self, file_path: Path):
        try:
            # 1. Create Torrent
            logger.info("Generating .torrent file...")
            torrent_path = create_torrent(
                source_path=file_path,
                output_path=settings.torrent_output_path,
                trackers=settings.trackers,
                piece_size=settings.piece_size,
                private=settings.private
            )
            logger.info(f"Torrent created at: {torrent_path}")
            
            # 2. Start Seeding LOCALLY
            logger.info("Starting local seeder (Aria2c)...")
            seed_id = self.seeder.start_seeding(torrent_path, file_path)
            if not seed_id:
                logger.error("Failed to start seeding. Aborting upload.")
                return

            # 3. Upload to Real-Debrid
            logger.info("Uploading to Real-Debrid...")
            try:
                torrent_id = self.rd.upload_torrent(torrent_path)
                logger.info(f"Upload successful. Torrent ID: {torrent_id}")
            except Exception as e:
                logger.error(f"RD Upload failed: {e}")
                self.seeder.stop_seeding(seed_id)
                return
            
            # 4. Start Download on RD
            try:
                self.rd.select_files(torrent_id)
                logger.info("Download started on Real-Debrid.")
            except Exception as e:
                logger.error(f"RD Selection failed: {e}")
                
            # 5. Track it
            with self.lock:
                self.active_items[seed_id] = {
                    "torrent_id": torrent_id,
                    "rd_status": "queued",
                    "path": file_path,
                    "added_at": time.time()
                }
            
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}", exc_info=True)

    def monitoring_loop(self):
        """
        Background loop to check RD status and stop seeding when done.
        """
        logger.info("Starting background monitoring loop...")
        while self.running:
            try:
                with self.lock:
                    # Create a copy to iterate
                    items_to_check = list(self.active_items.items())
                
                if not items_to_check:
                    time.sleep(5)
                    continue

                for seed_id, data in items_to_check:
                    tid = data["torrent_id"]
                    try:
                        info = self.rd.get_torrent_info(tid)
                        status = info.get("status")
                        progress = info.get("progress", 0)
                        
                        logger.debug(f"Checking {tid}: Status={status}, Progress={progress}%")
                        
                        if status == "downloaded":
                            logger.info(f"RD Download complete for {data['path']}. Stopping seeder.")
                            self.seeder.stop_seeding(seed_id)
                            with self.lock:
                                del self.active_items[seed_id]
                        elif status == "error" or status == "dead":
                            logger.error(f"RD Download failed for {data['path']} with status {status}. Stopping seeder.")
                            self.seeder.stop_seeding(seed_id)
                            with self.lock:
                                del self.active_items[seed_id]
                                
                    except Exception as e:
                        logger.error(f"Error checking status for {tid}: {e}")
                
                time.sleep(10) # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(10)

    def start(self):
        # Ensure watch directories
        if not settings.watch_path.exists():
            settings.watch_path.mkdir(parents=True, exist_ok=True)

        # Initialize Executor
        max_workers = settings.max_concurrent_uploads
        logger.info(f"Starting ThreadPoolExecutor with {max_workers} workers.")
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
            
        # Start Watcher
        watcher = DirectoryWatcher(settings.watch_path, self.process_new_file)
        watcher.start()
        
        # Start Monitoring Loop
        monitor_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
        monitor_thread.start()
        
        logger.info("Orchestrator started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
            logger.info("Stopping...")
            watcher.stop()
            # Stop all seeders
            for seed_id in self.seeder.get_all_handles():
                self.seeder.stop_seeding(seed_id)
            
            if self.executor:
                logger.info("Shutting down executor...")
                self.executor.shutdown(wait=False)

def start_watching():
    orchestrator = Orchestrator()
    orchestrator.start()
