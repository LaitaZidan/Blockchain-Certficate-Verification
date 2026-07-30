# ipfs_logic.py
from crypto.aes_utils import decrypt_data
from config import AES_SECRET_KEY
from utils.image_logic import regenerate_verified_certificate
from ipfs.ipfs_utils import upload_to_ipfs


def decrypt_and_regenerate(encrypted_data, certificate_id):
    """V9: the AES-decrypt + PNG-regenerate half of post-decision I/O. Split
    out from the IPFS upload so the single-verification path can run this
    synchronously (the response includes the regenerated image) while
    deferring only the IPFS upload."""
    decrypted = decrypt_data(encrypted_data, AES_SECRET_KEY)
    if not decrypted:
        raise ValueError("Dekripsi gagal")

    img_bytes, img_base64, qr_base64 = regenerate_verified_certificate(decrypted, certificate_id)

    return {
        "decrypted_data": decrypted,
        "img_bytes": img_bytes,
        "img_base64": img_base64,
        "qr_code": qr_base64,
    }


def upload_regenerated_to_ipfs(img_bytes):
    """V9: the IPFS-upload half of post-decision I/O - deferred, off the
    critical path for both single and batch verification."""
    ipfs = upload_to_ipfs(img_bytes)
    if not ipfs:
        raise ValueError("Upload ke IPFS gagal")
    return ipfs
