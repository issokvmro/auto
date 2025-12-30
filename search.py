import httpx
from config import API_BASE_URL, REQUEST_TIMEOUT, get_headers

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
