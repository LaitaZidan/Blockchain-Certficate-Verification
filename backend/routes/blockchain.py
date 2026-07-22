from flask import Blueprint, request, jsonify
from config import web3, contract
from utils.timing import timed

blockchain_bp = Blueprint("blockchain", __name__)

# Menyimpan signature ke blockchain
# Mengembalikan certificate_id hasil generate otomatis oleh smart contract
@timed("blockchain_submit")
def store_signature(signature: str) -> str:
    sender_address = web3.eth.accounts[0]
    tx_hash = contract.functions.addCertificate(signature).transact({'from': sender_address, 'gas': 2000000})
    print(f"📤 TX Hash: {tx_hash.hex()} - waiting confirmation...")
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"✅ Confirmed in block: {receipt.blockNumber}")
    
    certificate_counter = contract.functions.certificateCounter().call()
    certificate_id = f"CERT-{certificate_counter:03d}"
    return certificate_id

def get_certificate_data(certificate_id: str):
    try:
        is_valid, returned_id, returned_signature = contract.functions.getCertificate(certificate_id).call()
        return is_valid, returned_id, returned_signature
    except Exception as e:
        print(f"Blockchain read error: {e}")
        return False, "", ""