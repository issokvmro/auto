import httpx
from config import API_BASE_URL, DAB_EMAIL, DAB_PASSWORD, REQUEST_TIMEOUT, USER_AGENT, get_headers

class AuthError(Exception):
    pass

def login():
    """
    Authenticates with the DAB Music API and returns a dictionary of cookies.
    """
    # If a token is already provided in env, use it.
    # Note: In a real app we might want to validate it first.
    from config import DAB_TOKEN
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
                # debug_session.py proved that persistent cookies are required.
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
