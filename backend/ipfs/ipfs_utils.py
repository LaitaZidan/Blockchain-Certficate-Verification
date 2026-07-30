from config import GATEWAY_URL, IPFS_API
import requests

# V11: single `add` call, reusing one Session instead of opening a new
# connection per request; the MFS rm/cp round-trip is removed entirely -
# the /api/v0/add call already pins the file under its CID, so nothing else
# is needed to make it retrievable via the gateway.
_session = requests.Session()

def upload_to_ipfs(file_bytes, filename="certificate.png"):
    try:
        files = {'file': (filename, file_bytes)}
        res = _session.post(f"{IPFS_API}/api/v0/add", files=files)
        res.raise_for_status()
        cid = res.json()["Hash"]
        return {
            "cid": cid,
            "url": f"{GATEWAY_URL}{cid}"
        }
    except Exception as e:
        print(f"❌ IPFS upload error: {e}")
        return None