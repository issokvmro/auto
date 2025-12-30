import os
import httpx
from pathlib import Path
from config import API_BASE_URL, DOWNLOAD_DIR, REQUEST_TIMEOUT, get_headers

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
    # Verify FLAC availability if metadata is provided (if API supports checking format)
    # For now, we assume if we request download, we get best quality.
    
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
            # album = sanitize_filename(metadata.get('album', 'Unknown Album')) if metadata else 'Unknown Album' # Album not used in path anymore
            title = sanitize_filename(metadata.get('title', f'track_{track_id}')) if metadata else f'track_{track_id}'

            save_dir = DOWNLOAD_DIR
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # For now default to .flac since we see fmt=6. ideally we check content-type of the stream.
            ext = ".flac"
            file_path = save_dir / f"{artist} - {title}{ext}"
            
            # Stream the actual file
            # Note: The stream URL might not need our cookies/headers, but usually User-Agent is good.
            # AKAMAI tokens are usually in the URL itself.
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
                # We can use a simple generic get since covers are usually public
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

