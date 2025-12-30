import subprocess
import time
import logging
import uuid
import sys
from pathlib import Path
from typing import Dict, Optional

from .config import settings

logger = logging.getLogger(__name__)

class SeederManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        # We'll map a unique ID (or hash) directly to the process
        
    def start_seeding(self, torrent_path: Path, source_path: Path) -> str:
        """
        Starts seeding a torrent using aria2c.
        Returns a unique ID for this seeding process (we use info_hash logic generally, 
        but aria2 doesn't give it back easily on CLI start. We can use a UUID or generic ID).
        
        To simplify, we'll try to extract the hash if possible, or just return a UUID
        that the Core uses to map back to this process.
        """
        if not torrent_path.exists():
            logger.error(f"Torrent file not found: {torrent_path}")
            return None
        
        # Unique ID for tracking this instance
        seed_id = str(uuid.uuid4())
        
        # Directory where the actual file content lives
        # If source_path is C:/downloads/Movie.mkv, aria2c needs to look in C:/downloads/
        # when loading the torrent created from Movie.mkv
        save_dir = source_path.parent
        
        cmd = [
            settings.aria2c_binary,
            "--enable-dht=true",
            "--seed-ratio=0.0",   # Seed indefinitely (until we stop it)
            "--seed-time=0",
            "--file-allocation=none",
            "--check-integrity=false", # Skip check for speed
            f"--dir={save_dir}",
            str(torrent_path)
        ]
        
        logger.info(f"Starting aria2c: {' '.join(str(x) for x in cmd)}")
        
        log_file = open("aria2c_debug.log", "a")
        
        try:
            # Start process detached/background
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            self.processes[seed_id] = process
            logger.info(f"Aria2c started (ID: {seed_id})")
            return seed_id
            
        except FileNotFoundError:
            logger.critical("aria2c executable not found! Make sure it is in your PATH.")
            return None
        except Exception as e:
            logger.error(f"Failed to start aria2c: {e}")
            return None

    def stop_seeding(self, seed_id: str):
        if seed_id in self.processes:
            p = self.processes[seed_id]
            logger.info(f"Stopping aria2c process for ID: {seed_id}")
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            del self.processes[seed_id]

    def get_all_handles(self):
        return list(self.processes.keys())
