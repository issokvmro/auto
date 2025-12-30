import os
from pathlib import Path
from dotenv import load_dotenv

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
