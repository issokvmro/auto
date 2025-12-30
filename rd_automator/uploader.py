import logging
import os
from pathlib import Path
from typing import Optional
from .config import settings

logger = logging.getLogger(__name__)

try:
    import dropbox
    from dropbox.files import WriteMode, CommitInfo, UploadSessionCursor
except ImportError:
    dropbox = None

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
                
                # Dropbox links default to dl=0, we need dl=1 for direct download (though RD handles it mostly, dl=1 is safer)
                # Actually RD usually handles the standard link.
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
