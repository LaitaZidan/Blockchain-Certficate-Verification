import os
import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) 
keys_dir = os.path.join(base_dir, "keys")
os.makedirs(keys_dir, exist_ok=True)

private_key_path = os.path.join(keys_dir, "private_key.pem")
public_key_path = os.path.join(keys_dir, "public_key.pem")

# Fungsi untuk membuat kunci RSA jika belum ada
def generate_rsa_keys():
    if not os.path.exists(private_key_path) or not os.path.exists(public_key_path):
        print("Generating new RSA keys...")
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key = private_key.public_key()

        # Simpan private key
        with open(private_key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Simpan public key
        with open(public_key_path, "wb") as f:
            f.write(public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ))

        print("RSA keys generated successfully.")

# Fungsi untuk memuat kunci
_private_key_cache = None

def load_private_key():
    global _private_key_cache
    if _private_key_cache is None:
        with open(private_key_path, "rb") as f:
            _private_key_cache = serialization.load_pem_private_key(f.read(), password=None)
    return _private_key_cache

def load_public_key():
    with open(public_key_path, "rb") as f:
        return serialization.load_pem_public_key(f.read())

# Fungsi untuk membuat digital signature dari hash md5
def sign_data(data: str, private_key) -> str:
    signature = private_key.sign(
        data.encode(),
        padding.PKCS1v15(),
        hashes.MD5()
    )
    return base64.b64encode(signature).decode()

# Fungsi untuk memverifikasi signature
def verify_signature(data: str, signature_b64: str) -> bool:
    public_key = load_public_key()
    signature = base64.b64decode(signature_b64)
    try:
        public_key.verify(
            signature,
            data.encode(),
            padding.PKCS1v15(),
            hashes.MD5()
        )
        return True
    except Exception:
        return False
