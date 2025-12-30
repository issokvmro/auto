
import os
import sys
import time
import logging
import threading
import subprocess
import uuid
import yaml
import requests
import typer
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from rich.console import Console
from rich.table import Table

# Third-party imports that might need installation checks
try:
    from torrentool.api import Torrent
except ImportError:
    print("Error: 'torrentool' not found. Please pip install torrentool.")
    sys.exit(1)

try:
    import dropbox
    from dropbox.files import WriteMode, CommitInfo, UploadSessionCursor
except ImportError:
    dropbox = None

# =========================================================================================
# LOGGING SETUP
# =========================================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("rd_automator.log")
    ]
)
logger = logging.getLogger("rd_automator")
console = Console()

# =========================================================================================
# CONFIGURATION
# =========================================================================================
load_dotenv()

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        # Look for config in the same directory as this script
        base_dir = Path(__file__).parent.resolve()
        self.config_path = base_dir / config_path
        self.config_data = self._load_config()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f) or {}

    @property
    def rd_api_token(self) -> str:
        token = os.getenv("RD_API_TOKEN")
        if not token:
            # We'll allow it to run but it will fail on RD steps
            logger.warning("RD_API_TOKEN not found in environment variables.")
            return ""
        return token

    @property
    def watch_path(self) -> Path:
        path_str = self.config_data.get("watch_path", "./watch_folder")
        return Path(path_str).resolve()

    @property
    def torrent_output_path(self) -> Path:
        path_str = self.config_data.get("torrent_output_path", "./torrents")
        return Path(path_str).resolve()

    @property
    def trackers(self) -> List[str]:
        return self.config_data.get("trackers", [])

    @property
    def piece_size(self) -> Optional[int]:
        return self.config_data.get("piece_size")

    @property
    def private(self) -> bool:
        return bool(self.config_data.get("private", 0))

    @property
    def aria2c_binary(self) -> str:
        return os.getenv("ARIA2C_BINARY_PATH") or self.config_data.get("aria2c_binary_path", "aria2c")

    @property
    def upload_mode(self) -> str:
        return self.config_data.get("upload_mode", "torrent")

    @property
    def dropbox_token(self) -> str:
        return os.getenv("DROPBOX_ACCESS_TOKEN", "")

    @property
    def max_concurrent_uploads(self) -> int:
        return self.config_data.get("max_concurrent_uploads", 3)

    @property
    def upload_chunk_size(self) -> int:
        return self.config_data.get("upload_chunk_size", 64 * 1024 * 1024)

    @property
    def dropbox_app_key(self) -> str:
        return os.getenv("DROPBOX_APP_KEY", "")

    @property
    def dropbox_app_secret(self) -> str:
        return os.getenv("DROPBOX_APP_SECRET", "")

    @property
    def dropbox_refresh_token(self) -> str:
        return os.getenv("DROPBOX_REFRESH_TOKEN", "")

settings = Config()

# =========================================================================================
# DROPBOX UPLOADER
# =========================================================================================
class DropboxUploader:
    @staticmethod
    def _get_client() -> Optional['dropbox.Dropbox']:
        if not dropbox:
            logger.error("Dropbox library not found. Please install 'dropbox' package.")
            return None

        token = settings.dropbox_token
        refresh_token = settings.dropbox_refresh_token
        app_key = settings.dropbox_app_key
        app_secret = settings.dropbox_app_secret

        if refresh_token and app_key and app_secret:
            logger.info("Using Dropbox Refresh Token authentication.")
            return dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token
            )
        elif token:
            logger.info("Using existing Dropbox Access Token.")
            return dropbox.Dropbox(token)
        else:
            logger.error("Dropbox credentials not found! Need either Access Token OR (App Key + Secret + Refresh Token).")
            return None

    @staticmethod
    def upload_file(file_path: Path) -> Optional[str]:
        """
        Uploads a file to Dropbox.
        Returns the Shared Link URL if successful, None otherwise.
        """
        dbx = DropboxUploader._get_client()
        if not dbx:
            return None
            
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        file_size = file_path.stat().st_size
        CHUNK_SIZE = settings.upload_chunk_size
        
        destination_path = "/" + file_path.name
        
        logger.info(f"Uploading {file_path.name} to Dropbox ({file_size/1024/1024:.2f} MB)...")

        try:
            with open(file_path, "rb") as f:
                if file_size <= CHUNK_SIZE:
                    dbx.files_upload(f.read(), destination_path, mode=WriteMode('overwrite'))
                else:
                    # Chunked upload
                    upload_session_start_result = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
                    cursor = UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
                    commit = CommitInfo(path=destination_path, mode=WriteMode('overwrite'))

                    while f.tell() < file_size:
                        if (file_size - f.tell()) <= CHUNK_SIZE:
                            dbx.files_upload_session_finish(f.read(CHUNK_SIZE), cursor, commit)
                        else:
                            dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), cursor)
                            cursor.offset = f.tell()
                            
            logger.info("Dropbox Upload finished.")
            
            # Create shared link
            try:
                # Check if exists
                links = dbx.sharing_list_shared_links(path=destination_path, direct_only=True).links
                if links:
                    url = links[0].url
                else:
                    link_meta = dbx.sharing_create_shared_link_with_settings(destination_path)
                    url = link_meta.url
                
                logger.info(f"Dropbox Link: {url}")
                return url
                
            except dropbox.exceptions.ApiError as e:
                logger.error(f"Error creating shared link: {e}")
                return None

        except Exception as e:
            logger.error(f"Error uploading to Dropbox: {e}")
            return None

    @staticmethod
    def delete_file(file_name: str) -> bool:
        """
        Deletes a file from Dropbox by name (in root).
        """
        dbx = DropboxUploader._get_client()
        if not dbx:
            return False

        try:
            path = "/" + file_name
            logger.info(f"Deleting {path} from Dropbox...")
            dbx.files_delete_v2(path)
            logger.info("Dropbox file deleted successfully.")
            return True
        except Exception as e:
            logger.error(f"Error deleting file from Dropbox: {e}")
            return False

# =========================================================================================
# REAL-DEBRID CLIENT
# =========================================================================================
class RealDebridClient:
    BASE_URL = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return response.content
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error: {e}")
            raise

    def get_user_info(self) -> Dict[str, Any]:
        return self._request("GET", "/user")

    def upload_torrent(self, file_path: Path) -> str:
        if not file_path.exists():
            raise FileNotFoundError(f"Torrent file not found: {file_path}")

        with open(file_path, "rb") as f:
            data = self._request("PUT", "/torrents/addTorrent", data=f)
            
        if "id" not in data:
            raise ValueError(f"Failed to upload torrent, no ID returned. Response: {data}")
            
        return data["id"]

    def get_torrent_info(self, torrent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/torrents/info/{torrent_id}")

    def select_files(self, torrent_id: str, file_ids: str = "all") -> None:
        self._request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": file_ids})

    def unrestrict_link(self, link: str) -> str:
        data = self._request("POST", "/unrestrict/link", data={"link": link})
        return data

# =========================================================================================
# TORRENT CREATOR
# =========================================================================================
def create_torrent(
    source_path: Path,
    output_path: Path,
    trackers: List[str] = None,
    piece_size: Optional[int] = None,
    private: bool = False
) -> Path:
    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")

    output_path.mkdir(parents=True, exist_ok=True)
    torrent_name = source_path.name
    torrent_file_path = output_path / f"{torrent_name}.torrent"

    t = Torrent.create_from(str(source_path))
    if trackers:
        t.announce_urls = trackers
    if private:
        t.private = True
        
    t.to_file(str(torrent_file_path))
    return torrent_file_path

# =========================================================================================
# SEEDER MANAGER
# =========================================================================================
class SeederManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        
    def start_seeding(self, torrent_path: Path, source_path: Path) -> str:
        if not torrent_path.exists():
            logger.error(f"Torrent file not found: {torrent_path}")
            return None
        
        seed_id = str(uuid.uuid4())
        save_dir = source_path.parent
        
        cmd = [
            settings.aria2c_binary,
            "--enable-dht=true",
            "--seed-ratio=0.0",
            "--seed-time=0",
            "--file-allocation=none",
            "--check-integrity=false",
            f"--dir={save_dir}",
            str(torrent_path)
        ]
        
        logger.info(f"Starting aria2c: {' '.join(str(x) for x in cmd)}")
        
        try:
             with open("aria2c_debug.log", "a") as log_file:
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

# =========================================================================================
# WATCHER
# =========================================================================================
class NewFileHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None]):
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        logger.info(f"Detected new file: {path}")
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

# =========================================================================================
# ORCHESTRATOR
# =========================================================================================
class Orchestrator:
    def __init__(self):
        self.rd = RealDebridClient(token=settings.rd_api_token)
        self.seeder = SeederManager()
        self.active_items: Dict[str, Dict] = {} 
        self.lock = threading.Lock()
        self.running = True
        self.executor = None

    def _wait_for_file_stability(self, file_path: Path, debounce_seconds=2) -> bool:
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
        if self.executor:
            self.executor.submit(self._process_file_task, file_path)
        else:
            logger.warning("Executor not started! processing sync.")
            self._process_file_task(file_path)

    def _process_file_task(self, file_path: Path):
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
        url = DropboxUploader.upload_file(file_path)
        if not url:
            logger.error("Hoster upload failed. Aborting.")
            return

        logger.info(f"Unrestricting link: {url}")
        try:
            data = self.rd.unrestrict_link(url)
            logger.info(f"Unrestrict successful! Download ID: {data.get('id')}")
            
            download_link = data.get("download")
            if download_link:
                log_line = f"{file_path.name} - {download_link}\n"
                try:
                    with open("unrestricted_links.txt", "a", encoding="utf-8") as f:
                        f.write(log_line)
                    logger.info("Saved link to unrestricted_links.txt")
                except Exception as e:
                    logger.error(f"Failed to write to link log: {e}")

            logger.info("Cleaning up Dropbox to save space...")
            DropboxUploader.delete_file(file_path.name)

        except Exception as e:
            logger.error(f"Unrestrict failed: {e}")

    def _process_torrent_mode(self, file_path: Path):
        try:
            logger.info("Generating .torrent file...")
            torrent_path = create_torrent(
                source_path=file_path,
                output_path=settings.torrent_output_path,
                trackers=settings.trackers,
                piece_size=settings.piece_size,
                private=settings.private
            )
            logger.info(f"Torrent created at: {torrent_path}")
            
            logger.info("Starting local seeder (Aria2c)...")
            seed_id = self.seeder.start_seeding(torrent_path, file_path)
            if not seed_id:
                logger.error("Failed to start seeding. Aborting upload.")
                return

            logger.info("Uploading to Real-Debrid...")
            try:
                torrent_id = self.rd.upload_torrent(torrent_path)
                logger.info(f"Upload successful. Torrent ID: {torrent_id}")
            except Exception as e:
                logger.error(f"RD Upload failed: {e}")
                self.seeder.stop_seeding(seed_id)
                return
            
            try:
                self.rd.select_files(torrent_id)
                logger.info("Download started on Real-Debrid.")
            except Exception as e:
                logger.error(f"RD Selection failed: {e}")
                
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
        logger.info("Starting background monitoring loop...")
        while self.running:
            try:
                with self.lock:
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
                
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(10)

    def start(self):
        if not settings.watch_path.exists():
            settings.watch_path.mkdir(parents=True, exist_ok=True)

        max_workers = settings.max_concurrent_uploads
        logger.info(f"Starting ThreadPoolExecutor with {max_workers} workers.")
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
            
        watcher = DirectoryWatcher(settings.watch_path, self.process_new_file)
        watcher.start()
        
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
            for seed_id in self.seeder.get_all_handles():
                self.seeder.stop_seeding(seed_id)
            if self.executor:
                logger.info("Shutting down executor...")
                self.executor.shutdown(wait=False)

def start_watching():
    orchestrator = Orchestrator()
    orchestrator.start()

# =========================================================================================
# CLI / MAIN
# =========================================================================================
app = typer.Typer(help="Real-Debrid Torrent Automator CLI (Consolidated)")

@app.command()
def start():
    """
    Start the directory watcher.
    """
    console.print(f"[green]Starting watcher on {settings.watch_path}[/green]")
    console.print(f"[blue]Outputting .torrent files to {settings.torrent_output_path}[/blue]")
    try:
        start_watching()
    except KeyboardInterrupt:
        console.print("[yellow]Stopping...[/yellow]")

@app.command()
def status():
    """
    Show recent activity or status.
    """
    try:
        rd = RealDebridClient(token=settings.rd_api_token)
        user_info = rd.get_user_info()
        console.print(f"[bold]User:[/bold] {user_info.get('username')}")
        console.print(f"[bold]Premium:[/bold] {user_info.get('type')}")
        console.print(f"[bold]Expiration:[/bold] {user_info.get('expiration')}")
        
    except Exception as e:
        console.print(f"[red]Error fetching status: {e}[/red]")
        console.print("[yellow]Check your RD_API_TOKEN in .env[/yellow]")

@app.command()
def config():
    """
    Opens the configuration file in the default editor.
    """
    config_path = Path("config.yaml")
    if not config_path.exists():
        console.print("[red]Config file config.yaml not found![/red]")
        return
    
    console.print(f"Opening {config_path}...")
    if os.name == 'nt':
        os.startfile(config_path)
    elif sys.platform == 'darwin':
        subprocess.call(('open', config_path))
    else:
        subprocess.call(('xdg-open', config_path))

def print_banner():
    banner = r"""
__________________       _____          __                         __                
\______   \______ \     /  _  \  __ ___/  |_  ____   _____ _____ _/  |_  ___________ 
 |       _/|    |  \   /  /_\  \|  |  \   __\/  _ \ /     \\__  \\   __\/  _ \_  __ \
 |    |   \|    `   \ /    |    \  |  /|  | (  <_> )  Y Y  \/ __ \|  | (  <_> )  | \/
 |____|_  /_______  / \____|__  /____/ |__|  \____/|__|_|  (____  /__|  \____/|__|   
        \/        \/          \/                         \/     \/                      
                                                                    
         Real-Debrid Automator (Consolidated)
    """
    print(banner)
    print("\n" + "="*70)

if __name__ == "__main__":
    print_banner()
    app()
