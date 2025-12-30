import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect

def get_refresh_token():
    print("---------------------------------------------------------")
    print("Dropbox Refresh Token Generator")
    print("---------------------------------------------------------")
    print("1. Go to https://www.dropbox.com/developers/apps")
    print("2. Click 'Create App', choose 'Scoped Access' and 'Full Dropbox' (or 'App Folder').")
    print("3. Go to the 'Permissions' tab and check the following:")
    print("   - files.content.write")
    print("   - files.content.read")
    print("   - sharing.write")
    print("   - Click 'Submit' to save changes.")
    print("4. Go to the 'Settings' tab.")
    
    app_key = input("Enter your App Key: ").strip()
    app_secret = input("Enter your App Secret: ").strip()

    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key, 
        app_secret, 
        token_access_type='offline'
    )

    authorize_url = auth_flow.start()
    print("\n1. Go to: " + authorize_url)
    print("2. Click 'Allow' (you might need to log in).")
    print("3. Copy the authorization code.")
    
    auth_code = input("\nEnter the authorization code here: ").strip()

    try:
        oauth_result = auth_flow.finish(auth_code)
        print("\n---------------------------------------------------------")
        print("SUCCESS! Update your .env file with the following:")
        print("---------------------------------------------------------")
        print(f"DROPBOX_APP_KEY={app_key}")
        print(f"DROPBOX_APP_SECRET={app_secret}")
        print(f"DROPBOX_REFRESH_TOKEN={oauth_result.refresh_token}")
        print("---------------------------------------------------------")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    get_refresh_token()
