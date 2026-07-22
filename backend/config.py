import os
from dotenv import load_dotenv
import json
from web3 import Web3

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# NOTE: GANACHE_URL is expected to point at a local Ganache instance running in
# "instamine" mode (transactions mined immediately). Receipt-wait latency (B6)
# is tuned against that assumption; it is an experimental variable, not a
# production deployment setting.
GANACHE_URL = os.getenv("GANACHE_URL")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
AES_SECRET_KEY = os.getenv("AES_SECRET_KEY")
GATEWAY_URL = os.getenv("GATEWAY_URL")
IPFS_API = os.getenv("IPFS_API")
SECRET_KEY = os.getenv("SECRET_KEY")
web3 = Web3(Web3.HTTPProvider(GANACHE_URL))

# Cek koneksi ke blockchain
if web3.is_connected():
    print("Connected to Etherium network")
else:
    print("Failed to connect to Etherium network")

# Load ABI contract dengan path absolut
base_dir = os.path.abspath(os.path.dirname(__file__))
contract_path = os.path.join(base_dir, "../blockchain/build/contracts/CertificateVerification.json")

if not os.path.exists(contract_path):
    raise FileNotFoundError("Smart contract ABI file not found!")

with open(contract_path) as f:
    contract_json = json.load(f)
    contract_abi = contract_json['abi']

contract = web3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)