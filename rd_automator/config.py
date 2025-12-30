import os
import yaml
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.config_data = self._load_config()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            # Fallback defaults if no config file
            return {}
        
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f) or {}

    @property
    def rd_api_token(self) -> str:
        token = os.getenv("RD_API_TOKEN")
        if not token:
            raise ValueError("RD_API_TOKEN not found in environment variables.")
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
        # Check env first, then config, then default "aria2c"
        return os.getenv("ARIA2C_BINARY_PATH") or self.config_data.get("aria2c_binary_path", "aria2c")

    @property
    def upload_mode(self) -> str:
        # Options: "torrent", "hoster"
        return self.config_data.get("upload_mode", "torrent")

    @property
    def dropbox_token(self) -> str:
        return os.getenv("DROPBOX_ACCESS_TOKEN", "")

    @property
    def max_concurrent_uploads(self) -> int:
        return self.config_data.get("max_concurrent_uploads", 3)

    @property
    def upload_chunk_size(self) -> int:
        # Default to 64MB (64 * 1024 * 1024)
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

# Global config instance (can be re-initialized if needed)
settings = Config()
