import argparse
import sys
import logging
from auth import login, AuthError
from search import search, SearchError
from downloader import download_track, DownloadError
from config import DAB_EMAIL
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# Force UTF-8 stdout for emojis on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="DAB Music Downloader CLI")
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
    # Optional metadata arguments to avoid re-fetching details if the user knows them, 
    # though typically we might fetch track info first.
    dl_parser.add_argument("--artist", help="Artist name (for folder structure)", default="Unknown Artist")
    dl_parser.add_argument("--album", help="Album name (for folder structure)", default="Unknown Album")
    dl_parser.add_argument("--title", help="Track title (for filename)", default=None)

    # Batch Command
    batch_parser = subparsers.add_parser("batch", help="Batch download from file")
    batch_parser.add_argument("file", help="Path to text file with song queries")

    # Status Command
    status_parser = subparsers.add_parser("status", help="Show recent actions/status")

    args = parser.parse_args()

    if args.command == "login":
        try:
            print("Authenticating...")
            cookies = login()
            print(f"Login Successful! Cookies acquired for user: {DAB_EMAIL}")
            # In a persistent CLI we might save the cookies to a file here.
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

                    width = 40
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
        # Future: Read from a log file if we implement persistent logging.

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
