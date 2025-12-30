import os
import sys
import logging
import argparse
from pathlib import Path

# Third-party imports
try:
    import httpx
    from dotenv import load_dotenv
except ImportError:
    print("Error: Missing required dependencies. Please install them:")
    print("pip install httpx python-dotenv mutagen")
    sys.exit(1)

# --- CONFIGURATION (from config.py) ---
# Load environment variables
load_dotenv()

# API Configuration
BASE_URL = "https://dab.yeet.su"
API_BASE_URL = f"{BASE_URL}/api"

# Credential Configuration
DAB_EMAIL = os.getenv("DAB_EMAIL", os.getenv("DAB_USERNAME")) # Support both for backward compat
DAB_PASSWORD = os.getenv("DAB_PASSWORD")
DAB_TOKEN = os.getenv("DAB_TOKEN")

# Download Configuration
# Default to "watch_folder" in the current working directory
DEFAULT_DOWNLOAD_DIR = Path.cwd() / "watch_folder"
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))

# Request Configuration
USER_AGENT = "DAB-Downloader-CLI/1.0"
REQUEST_TIMEOUT = 30  # seconds

def get_headers():
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    return headers

# --- AUTH MODULE (from auth.py) ---
class AuthError(Exception):
    pass

def login():
    """
    Authenticates with the DAB Music API and returns a dictionary of cookies.
    """
    # If a token is already provided in env, use it.
    if DAB_TOKEN:
        return DAB_TOKEN

    if not DAB_EMAIL or not DAB_PASSWORD:
        raise AuthError("Credentials missing. Please set DAB_EMAIL and DAB_PASSWORD (or DAB_TOKEN) in .env file.")

    url = f"{API_BASE_URL}/auth/login"
    
    # Payload structure is assumed based on standard practices
    payload = {
        "email": DAB_EMAIL,
        "password": DAB_PASSWORD
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(url, json=payload, headers={"User-Agent": USER_AGENT})
            
            if response.status_code == 200:
                # We need all cookies, not just the session or token.
                cookies = dict(response.cookies)
                if not cookies:
                     raise AuthError("Login successful but no cookies received.")
                return cookies
            elif response.status_code == 401:
                raise AuthError("Invalid username or password.")
            else:
                raise AuthError(f"Login failed (Status {response.status_code}): {response.text}")

    except httpx.RequestError as e:
        raise AuthError(f"Network error during login: {str(e)}")

# --- SEARCH MODULE (from search.py) ---
class SearchError(Exception):
    pass

def search(query, cookies):
    """
    Searches for music using the DAB Music API.
    """
    url = f"{API_BASE_URL}/search"
    
    # Parameters assumed based on standard search APIs
    params = {
        "q": query,
        "type": "track",  # Defaulting to track search
        "limit": 20
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            headers = get_headers()
            response = client.get(url, params=params, headers=headers, cookies=cookies)
            
            if response.status_code == 200:
                data = response.json()
                # Return the list of results directly or the whole object if structure is unknown
                # Added 'tracks' based on debugging
                return data.get("tracks", data.get("data", data.get("results", [])))
            elif response.status_code == 401:
                raise SearchError("Authentication token expired or invalid.")
            else:
                raise SearchError(f"Search failed (Status {response.status_code}): {response.text}")

    except httpx.RequestError as e:
        raise SearchError(f"Network error during search: {str(e)}")

# --- DOWNLOADER MODULE (from downloader.py) ---
class DownloadError(Exception):
    pass

def sanitize_filename(name):
    """
    Sanitize a string to be safe for filenames.
    """
    return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()

def download_track(track_id, cookies, metadata=None):
    """
    Downloads a track by ID.
    cookies: Dictionary of authentication cookies.
    metadata: Optional dictionary with 'artist', 'album', 'title' to organize files.
    """
    # Step 1: Get download URL
    stream_url_endpoint = f"{API_BASE_URL}/stream"
    params = {"trackId": track_id}
    
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            headers = get_headers()
            
            # Fetch Stream URL
            response = client.get(stream_url_endpoint, params=params, headers=headers, cookies=cookies)
            if response.status_code != 200:
                 if response.status_code == 403:
                     raise DownloadError("Permission denied. You may not be entitled to download this track.")
                 raise DownloadError(f"Failed to get stream URL (Status {response.status_code}): {response.text}")
            
            data = response.json()
            download_url = data.get("url")
            if not download_url:
                raise DownloadError("API response did not contain a download URL.")

            # Step 2: Download the file
            # Determine filename and path
            artist = sanitize_filename(metadata.get('artist', 'Unknown Artist')) if metadata else 'Unknown Artist'
            title = sanitize_filename(metadata.get('title', f'track_{track_id}')) if metadata else f'track_{track_id}'

            save_dir = DOWNLOAD_DIR
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # For now default to .flac since we see fmt=6. ideally we check content-type of the stream.
            ext = ".flac"
            file_path = save_dir / f"{artist} - {title}{ext}"
            
            # Stream the actual file
            with client.stream("GET", download_url, headers={"User-Agent": headers["User-Agent"]}) as dl_response:
                if dl_response.status_code != 200:
                    raise DownloadError(f"File download failed (Status {dl_response.status_code})")
                
                total_size = int(dl_response.headers.get("content-length", 0))
                downloaded_size = 0
                
                with open(file_path, "wb") as f:
                    for chunk in dl_response.iter_bytes():
                        f.write(chunk)
                        downloaded_size += len(chunk)
                
                # Check integrity if content-length was provided
                if total_size > 0 and downloaded_size != total_size:
                    # Delete partial file?
                    os.remove(file_path)
                    raise DownloadError(f"Incomplete download. Expected {total_size} bytes, got {downloaded_size} bytes.")
                
    except httpx.RequestError as e:
        raise DownloadError(f"Network error during download: {str(e)}")
    except OSError as e:
        raise DownloadError(f"File system error: {str(e)}")
    
    # Step 3: Tag the file
    try:
        from mutagen.flac import FLAC, Picture
        audio = FLAC(file_path)
        audio['title'] = metadata.get('title', 'Unknown Title')
        audio['artist'] = metadata.get('artist', 'Unknown Artist')
        audio['album'] = metadata.get('album', 'Unknown Album')
        
        cover_url = metadata.get('cover_url')
        if cover_url:
            try:
                # Reuse existing client logic? better to just fresh request for the image
                with httpx.Client(timeout=30) as img_client:
                    img_resp = img_client.get(cover_url)
                    if img_resp.status_code == 200:
                        image_data = img_resp.content
                        
                        pic = Picture()
                        pic.type = 3 # Front Cover
                        pic.mime = "image/jpeg" # Assuming JPEG usually, could check header
                        if image_data.startswith(b'\x89PNG'):
                             pic.mime = "image/png"
                        pic.desc = "Cover"
                        pic.data = image_data
                        
                        audio.add_picture(pic)
            except Exception as e:
                print(f"Warning: Failed to download/embed cover art: {e}")

        audio.save()
    except ImportError:
        print("Warning: mutagen not installed. Skipping metadata tagging.")
    except Exception as e:
        print(f"Warning: Metadata tagging failed: {e}")
    
    return str(file_path)

# --- CLI MODULE (from dab.py) ---

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# Force UTF-8 stdout for emojis on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="DAB Music Downloader CLI (Single File)")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Login Command
    login_parser = subparsers.add_parser("login", help="Validate credentials")

    # Search Command
    search_parser = subparsers.add_parser("search", help="Search for music")
    search_parser.add_argument("query", help="Search query (Song name, Artist)")
    search_parser.add_argument("--download", "-d", action="store_true", help="Automatically download the first result")

    # Download Command
    dl_parser = subparsers.add_parser("download", help="Download a track")
    dl_parser.add_argument("track_id", help="ID of the track to download")
    dl_parser.add_argument("--artist", help="Artist name (for folder structure)", default="Unknown Artist")
    dl_parser.add_argument("--album", help="Album name (for folder structure)", default="Unknown Album")
    dl_parser.add_argument("--title", help="Track title (for filename)", default=None)

    # Batch Command
    batch_parser = subparsers.add_parser("batch", help="Batch download from file")
    batch_parser.add_argument("file", help="Path to text file with song queries")

    # Status Command
    status_parser = subparsers.add_parser("status", help="Show recent actions/status")

    args = parser.parse_args()

    # If no command is provided, print help
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "login":
        try:
            print("Authenticating...")
            cookies = login()
            print(f"Login Successful! Cookies acquired for user: {DAB_EMAIL}")
        except AuthError as e:
            print(f"Login Failed: {e}")
            sys.exit(1)

    elif args.command == "batch":
        filepath = Path(args.file)
        if not filepath.exists():
            print(f"Error: File not found: {filepath}")
            sys.exit(1)
            
        try:
            cookies = login()
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            
            print(f"Found {len(lines)} queries in batch file.")
            
            for i, query in enumerate(lines, 1):
                print(f"\n[{i}/{len(lines)}] Processing: {query}")
                try:
                    results = search(query, cookies)
                    if not results:
                        print(f"  No results found for '{query}'")
                        continue
                        
                    # Download first result
                    first_track = results[0]
                    tid = first_track.get('id')
                    if not tid:
                         print("  Skipping: Could not determine Track ID")
                         continue

                    artist = first_track.get('artist', {}).get('name', 'Unknown') if isinstance(first_track.get('artist'), dict) else first_track.get('artist', 'Unknown')
                    title = first_track.get('title', 'Unknown')
                    album_data = first_track.get('album', {})
                    album = album_data.get('name', 'Unknown') if isinstance(album_data, dict) else first_track.get('album', 'Unknown')
                    
                    # Try to find a cover art URL
                    cover_url = None
                    if isinstance(album_data, dict):
                        cover_url = album_data.get('cover_xl') or album_data.get('cover_big') or album_data.get('cover_medium') or album_data.get('cover_small') or album_data.get('cover')

                    print(f"  Downloading: {artist} - {title}")
                    
                    metadata = {
                        'artist': artist,
                        'album': album,
                        'title': title,
                        'cover_url': cover_url
                    }
                    path = download_track(tid, cookies, metadata)
                    print(f"  Done✅")

                except (SearchError, DownloadError) as e:
                    print(f"  Failed: {e}")
                except Exception as e:
                    print(f"  Unexpected error: {e}")
                    
        except AuthError as e:
             print(f"Login Failed: {e}")
             sys.exit(1)
        except Exception as e:
             print(f"Batch processing error: {e}")
             sys.exit(1)

    elif args.command == "search":
        try:
            # Auto-login to get cookies
            cookies = login()
            print(f"Searching for '{args.query}'...")
            results = search(args.query, cookies)
            
            if not results:
                print("No results found.")
            else:
                if args.download:
                    # Download the first result
                    first_track = results[0]
                    tid = first_track.get('id')
                    if not tid:
                        print("Error: Could not determine Track ID from search result.")
                        sys.exit(1)
                        
                    artist = first_track.get('artist', {}).get('name', 'Unknown') if isinstance(first_track.get('artist'), dict) else first_track.get('artist', 'Unknown')
                    title = first_track.get('title', 'Unknown')
                    album_data = first_track.get('album', {})
                    album = album_data.get('name', 'Unknown') if isinstance(album_data, dict) else first_track.get('album', 'Unknown')
                    
                    # Try to find a cover art URL
                    cover_url = None
                    if isinstance(album_data, dict):
                        cover_url = album_data.get('cover_xl') or album_data.get('cover_big') or album_data.get('cover_medium') or album_data.get('cover_small') or album_data.get('cover')

                    print(f"\nFound {len(results)} results. Downloading first match:")
                    print(f"{artist} - {title} ({album})")
                    
                    metadata = {
                        'artist': artist,
                        'album': album,
                        'title': title,
                        'cover_url': cover_url
                    }
                    
                    try:
                        path = download_track(tid, cookies, metadata)
                        print(f"Success! Saved to: {path}")
                    except DownloadError as de:
                        print(f"Download failed: {de}")
                        sys.exit(1)
                        
                else:
                    # Basic display formatting
                    print(f"{'ID':<10} | {'Artist':<20} | {'Title':<30} | {'Album':<20}")
                    print("-" * 88)
                    for item in results:
                        # Adjust keys based on actual API response
                        tid = item.get('id', 'N/A')
                        artist = item.get('artist', {}).get('name', 'Unknown') if isinstance(item.get('artist'), dict) else item.get('artist', 'Unknown')
                        title = item.get('title', 'Unknown')
                        album = item.get('album', {}).get('name', 'Unknown') if isinstance(item.get('album'), dict) else item.get('album', 'Unknown')
                        print(f"{tid:<10} | {artist[:18]:<20} | {title[:28]:<30} | {album[:18]:<20}")

        except (AuthError, SearchError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif args.command == "download":
        try:
            cookies = login()
            print(f"initiating download for Track ID: {args.track_id}...")
            
            # Construct metadata for file saving
            metadata = {
                'artist': args.artist,
                'album': args.album,
                'title': args.title
            }
            
            path = download_track(args.track_id, cookies, metadata)
            print(f"Success! Saved to: {path}")
            
        except (AuthError, DownloadError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif args.command == "status":
        print("DAB Music Downloader CLI is ready.")
        print("To monitor logs, check the console output of previous commands.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
