try:
    import libtorrent
    print("Success: import libtorrent")
except ImportError:
    print("Fail: import libtorrent")

try:
    import lbry_libtorrent
    print("Success: import lbry_libtorrent")
except ImportError:
    print("Fail: import lbry_libtorrent")

import pkg_resources
try:
    dist = pkg_resources.get_distribution("lbry-libtorrent")
    print(f"Installed: {dist.key} {dist.version}")
except Exception as e:
    print(f"Distribution not found: {e}")
