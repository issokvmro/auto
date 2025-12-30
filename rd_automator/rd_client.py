import requests
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from .config import settings

logger = logging.getLogger(__name__)

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
        """
        Uploads a .torrent file to Real-Debrid.
        Returns the Torrent ID.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Torrent file not found: {file_path}")

        with open(file_path, "rb") as f:
            # The API expects raw binary data in the body for PUT, not multipart/form-data
            data = self._request("PUT", "/torrents/addTorrent", data=f)
            
        if "id" not in data:
            raise ValueError(f"Failed to upload torrent, no ID returned. Response: {data}")
            
        return data["id"]

    def get_torrent_info(self, torrent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/torrents/info/{torrent_id}")

    def select_files(self, torrent_id: str, file_ids: str = "all") -> None:
        """
        Selects files to start the torrent.
        'all' selects all available files.
        """
        self._request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": file_ids})

    def add_magnet(self, magnet_link: str) -> str:
        data = self._request("POST", "/torrents/addMagnet", data={"magnet": magnet_link})
        return data["id"]

    def unrestrict_link(self, link: str) -> str:
        """
        Unrestricts a hoster link.
        Returns the download string/object details.
        """
        data = self._request("POST", "/unrestrict/link", data={"link": link})
        return data
