import httpx
from config import API_BASE_URL, DAB_EMAIL, DAB_PASSWORD, USER_AGENT

def debug_session():
    url = f"{API_BASE_URL}/auth/login"
    payload = {
        "email": DAB_EMAIL,
        "password": DAB_PASSWORD
    }

    # Use a persistent client to automatically handle cookies
    with httpx.Client() as client:
        # 1. Login
        print(f"Logging in to {url}...")
        resp = client.post(url, json=payload, headers={"User-Agent": USER_AGENT})
        print(f"Login Status: {resp.status_code}")
        print(f"Cookies after login: {resp.cookies}")
        
        if resp.status_code != 200:
            print(f"Login failed: {resp.text}")
            return

        # 2. Search
        search_url = f"{API_BASE_URL}/search"
        params = {"q": "Rick Astley", "type": "track", "limit": 1}
        print(f"Searching {search_url}...")
        
        resp_search = client.get(search_url, params=params, headers={"User-Agent": USER_AGENT})
        print(f"Search Status: {resp_search.status_code}")
        if resp_search.status_code == 200:
            print("Search Success!")
            print(resp_search.json())
        else:
            print(f"Search failed: {resp_search.text}")

if __name__ == "__main__":
    debug_session()
