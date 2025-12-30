import os
import sys
import logging
import time
import requests
import httpx
from pathlib import Path
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

# Try importing dropbox, but don't fail immediately if missing (though it is required for this script)
try:
    import dropbox
    from dropbox.files import WriteMode, CommitInfo, UploadSessionCursor
except ImportError:
    print("Error: 'dropbox' library not found. Please pip install dropbox.")
    sys.exit(1)

# Try importing mutagen
try:
    from mutagen.flac import FLAC, Picture
except ImportError:
    print("Warning: 'mutagen' library not found. Metadata tagging will be skipped.")

# =========================================================================================
# LOGGING SETUP
# =========================================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("unified_automator.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("UnifiedAuto")

# =========================================================================================
# CONFIGURATION
# =========================================================================================
load_dotenv()

class Config:
    # DAB Config
    DAB_BASE_URL = "https://dab.yeet.su"
    DAB_API_URL = f"{DAB_BASE_URL}/api"
    # Support both naming conventions from previous files
    DAB_EMAIL = os.getenv("DAB_EMAIL") or os.getenv("DAB_USERNAME")
    DAB_PASSWORD = os.getenv("DAB_PASSWORD")
    DAB_TOKEN = os.getenv("DAB_TOKEN")
    
    # RD Config
    RD_API_TOKEN = os.getenv("RD_API_TOKEN")
    
    # Dropbox Config
    DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", "")
    DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
    DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
    DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")
    UPLOAD_CHUNK_SIZE = 64 * 1024 * 1024

    # System Config
    DOWNLOAD_DIR = Path.cwd() / "downloads"
    USER_AGENT = "DAB-Downloader-CLI/1.0"
    REQUEST_TIMEOUT = 30

settings = Config()

def check_config():
    missing = []
    if not (settings.DAB_TOKEN or (settings.DAB_EMAIL and settings.DAB_PASSWORD)):
        missing.append("DAB_EMAIL/PASSWORD or DAB_TOKEN")
    if not settings.RD_API_TOKEN:
        missing.append("RD_API_TOKEN")
    if not (settings.DROPBOX_TOKEN or (settings.DROPBOX_REFRESH_TOKEN and settings.DROPBOX_APP_KEY)):
        missing.append("DROPBOX Credentials")
    
    if missing:
        logger.error(f"Missing configuration: {', '.join(missing)}")
        sys.exit(1)

# =========================================================================================
# DAB MUSIC CLIENT
# =========================================================================================
from curl_cffi import requests as cffi_requests

# =========================================================================================
# DAB MUSIC CLIENT (Cloudflare Bypass Edition)
# =========================================================================================
class DABClient:
    def __init__(self):
        self.cookies = {}
        # We might need to persist the session to keep cookies/headers
        self.session = cffi_requests.Session(impersonate="chrome")

    def login(self) -> Dict:
        """Authenticates with DAB and returns cookies."""
        if settings.DAB_TOKEN and isinstance(settings.DAB_TOKEN, dict):
             self.session.cookies.update(settings.DAB_TOKEN)
             return settings.DAB_TOKEN

        logger.info(f"Logging in to DAB as {settings.DAB_EMAIL}...")
        url = f"{settings.DAB_API_URL}/auth/login"
        payload = {"email": settings.DAB_EMAIL, "password": settings.DAB_PASSWORD}

        try:
            # impersonate="chrome" is key here
            response = self.session.post(url, json=payload)
            
            if response.status_code == 200:
                self.cookies = dict(response.cookies)
                if not self.cookies:
                    # Sometimes cookies are set in the session but not returned explicitly in some weird ways,
                    # but usually response.cookies is fine.
                    # Let's double check session cookies
                    self.cookies = dict(self.session.cookies)
                
                if not self.cookies:
                     raise Exception("Login successful but no cookies received.")
                     
                logger.info("DAB Login successful.")
                return self.cookies
            elif response.status_code == 401:
                raise Exception("Invalid credentials.")
            elif response.status_code == 403:
                 raise Exception("Cloudflare blocked the login request (403).")
            else:
                raise Exception(f"Login failed: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"DAB Login Error: {e}")
            raise

    def search(self, query: str) -> List[Dict]:
        """Searches for a track."""
        url = f"{settings.DAB_API_URL}/search"
        params = {"q": query, "type": "track", "limit": 5}
        
        try:
            response = self.session.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("tracks", data.get("data", data.get("results", [])))
            elif response.status_code == 401:
                raise Exception("DAB Token expired.")
            else:
                raise Exception(f"Search failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Search Error: {e}")
            return []

    def download_track(self, track_id: str, metadata: Dict) -> Optional[Path]:
        """Downloads a track and saves it to local disk."""
        stream_url_endpoint = f"{settings.DAB_API_URL}/stream"
        params = {"trackId": track_id}

        try:
            # Get Stream URL
            resp = self.session.get(stream_url_endpoint, params=params)
            if resp.status_code != 200:
                raise Exception(f"Failed to get stream URL: {resp.status_code}")
            
            data = resp.json()
            download_url = data.get("url")
            if not download_url:
                raise Exception("No download URL in response.")

            # Prepare Filename
            def sanitize(n): return "".join(c for c in n if c.isalnum() or c in (' ', '-', '_')).strip()
            
            artist = sanitize(metadata.get('artist', 'Unknown'))
            title = sanitize(metadata.get('title', f'track_{track_id}'))
            filename = f"{artist} - {title}.flac"
            
            settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_path = settings.DOWNLOAD_DIR / filename
            
            logger.info(f"Downloading: {filename}")
            
            # Download File
            # stream=True is supported by curl_cffi
            resp = self.session.get(download_url, stream=True)
            if resp.status_code != 200:
                raise Exception(f"Stream download failed: {resp.status_code}")
            
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            # Tagging (keep using existing logic, maybe fetch cover with session too)
            self._tag_file(file_path, metadata)
            return file_path

        except Exception as e:
            logger.error(f"Download Error for {track_id}: {e}")
            return None

    def _tag_file(self, file_path: Path, metadata: Dict):
        try:
            if 'mutagen' not in sys.modules:
                return
            
            audio = FLAC(file_path)
            audio['title'] = metadata.get('title', 'Unknown')
            audio['artist'] = metadata.get('artist', 'Unknown')
            audio['album'] = metadata.get('album', 'Unknown')
            
            cover_url = metadata.get('cover_url')
            if cover_url:
                try:
                    # Use the same session for images, maybe faster/consistent
                    r = self.session.get(cover_url, timeout=10)
                    if r.status_code == 200:
                        pic = Picture()
                        pic.type = 3
                        pic.mime = "image/png" if r.content.startswith(b'\x89PNG') else "image/jpeg"
                        pic.desc = "Cover"
                        pic.data = r.content
                        audio.add_picture(pic)
                except Exception as e:
                    logger.warning(f"Could not fetch cover art: {e}")
            
            audio.save()
        except Exception as e:
            logger.warning(f"Tagging failed: {e}")

# =========================================================================================
# DROPBOX UPLOADER
# =========================================================================================
class DropboxUploader:
    @staticmethod
    def _get_client():
        if settings.DROPBOX_REFRESH_TOKEN and settings.DROPBOX_APP_KEY:
            return dropbox.Dropbox(
                app_key=settings.DROPBOX_APP_KEY,
                app_secret=settings.DROPBOX_APP_SECRET,
                oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN
            )
        return dropbox.Dropbox(settings.DROPBOX_TOKEN)

    @staticmethod
    def upload_file(file_path: Path) -> Optional[str]:
        if not file_path.exists():
            return None
        
        dbx = DropboxUploader._get_client()
        file_size = file_path.stat().st_size
        destination_path = "/" + file_path.name
        
        logger.info(f"Uploading {file_path.name} to Dropbox ({file_size/1024/1024:.2f} MB)...")
        
        try:
            with open(file_path, "rb") as f:
                if file_size <= settings.UPLOAD_CHUNK_SIZE:
                    dbx.files_upload(f.read(), destination_path, mode=WriteMode('overwrite'))
                else:
                    # Chunked upload
                    upload_session_start_result = dbx.files_upload_session_start(f.read(settings.UPLOAD_CHUNK_SIZE))
                    cursor = UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
                    commit = CommitInfo(path=destination_path, mode=WriteMode('overwrite'))

                    while f.tell() < file_size:
                        if (file_size - f.tell()) <= settings.UPLOAD_CHUNK_SIZE:
                            dbx.files_upload_session_finish(f.read(settings.UPLOAD_CHUNK_SIZE), cursor, commit)
                        else:
                            dbx.files_upload_session_append_v2(f.read(settings.UPLOAD_CHUNK_SIZE), cursor)
                            cursor.offset = f.tell()
            
            logger.info("Upload complete.")
            
            # Create Shared Link
            try:
                links = dbx.sharing_list_shared_links(path=destination_path, direct_only=True).links
                if links:
                    url = links[0].url
                else:
                    link_meta = dbx.sharing_create_shared_link_with_settings(destination_path)
                    url = link_meta.url
                return url
            except dropbox.exceptions.ApiError as e:
                logger.error(f"Error creating shared link: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Dropbox Upload Error: {e}")
            return None

    @staticmethod
    def delete_file(filename: str):
        dbx = DropboxUploader._get_client()
        try:
            dbx.files_delete_v2("/" + filename)
            logger.info(f"Deleted {filename} from Dropbox.")
        except Exception:
            pass

# =========================================================================================
# REAL-DEBRID CLIENT
# =========================================================================================
class RealDebridClient:
    BASE_URL = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def unrestrict_link(self, link: str) -> Optional[str]:
        url = f"{self.BASE_URL}/unrestrict/link"
        try:
            resp = requests.post(url, data={"link": link}, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("download")
        except Exception as e:
            logger.error(f"RD Unrestrict Error: {e}")
            return None

# =========================================================================================
# MAIN ORCHESTRATOR
# =========================================================================================
def process_batch(file_path: str):
    check_config()
    
    dab = DABClient()
    rd = RealDebridClient(settings.RD_API_TOKEN)
    
    # Login to DAB
    dab.login()
    
    if not Path(file_path).exists():
        logger.error(f"Songs file not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        songs = [line.strip() for line in f if line.strip()]

    logger.info(f"Found {len(songs)} songs to process.")

    for i, song_query in enumerate(songs, 1):
        logger.info(f"\n--- Processing [{i}/{len(songs)}]: {song_query} ---")
        
        # 1. Search
        results = dab.search(song_query)
        if not results:
            logger.warning(f"No results for: {song_query}")
            continue

        first_track = results[0]
        tid = first_track.get('id')
        
        # Extract Metadata
        artist_obj = first_track.get('artist', {})
        artist = artist_obj.get('name', 'Unknown') if isinstance(artist_obj, dict) else str(artist_obj)
        
        album_obj = first_track.get('album', {})
        album = album_obj.get('name', 'Unknown') if isinstance(album_obj, dict) else str(album_obj)
        title = first_track.get('title', 'Unknown')
        
        # Cover URL
        cover_url = None
        if isinstance(album_obj, dict):
            cover_url = album_obj.get('cover_xl') or album_obj.get('cover_big') or album_obj.get('cover')

        metadata = {'artist': artist, 'album': album, 'title': title, 'cover_url': cover_url}
        
        # 2. Download from DAB
        local_file = dab.download_track(tid, metadata)
        if not local_file:
            continue

        # 3. Upload to Dropbox
        dbx_link = DropboxUploader.upload_file(local_file)
        if not dbx_link:
            logger.error("Skipping RD step due to upload failure.")
            continue

        # 4. Unrestrict via Real-Debrid
        rd_link = rd.unrestrict_link(dbx_link)
        if rd_link:
            logger.info(f"SUCCESS! Unrestricted Link: {rd_link}")
            with open("unrestricted_links.txt", "a", encoding="utf-8") as out:
                out.write(f"{artist} - {title} : {rd_link}\n")
        
        # 5. Cleanup
        # Delete local file
        try:
            os.remove(local_file)
            logger.info("Deleted local file.")
        except Exception as e:
            logger.warning(f"Failed to delete local file: {e}")
        
        # Delete Dropbox file
        DropboxUploader.delete_file(local_file.name)

if __name__ == "__main__":
    songs_file = sys.argv[1] if len(sys.argv) > 1 else "songs.txt"
    try:
        process_batch(songs_file)
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
