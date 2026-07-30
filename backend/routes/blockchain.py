import json
from flask import Blueprint, request, jsonify
from config import web3, contract, SENDER_PRIVATE_KEY, RECEIPT_POLL_LATENCY, redis_client
from utils.timing import timed

blockchain_bp = Blueprint("blockchain", __name__)

GAS_LIMIT = 2000000

# B8: account derived locally from SENDER_PRIVATE_KEY (.env) instead of relying
# on the node's own unlocked account list.
_sender_account = web3.eth.account.from_key(SENDER_PRIVATE_KEY) if SENDER_PRIVATE_KEY else None


def _get_sender_address() -> str:
    if _sender_account is None:
        raise RuntimeError(
            "SENDER_PRIVATE_KEY is not configured in .env - set it to the private key "
            "of your local Ganache dev account (web3.eth.accounts[0])."
        )
    return _sender_account.address


def get_certificate_counter() -> int:
    """B4b: read the on-chain counter once; callers derive IDs locally from it."""
    return contract.functions.certificateCounter().call()


def get_next_nonce() -> int:
    """B1: fetch the sender's nonce once; callers assign it monotonically per tx."""
    return web3.eth.get_transaction_count(_get_sender_address(), "pending")


def format_certificate_id(start_counter: int, index: int) -> str:
    """B4b: deterministic ID from nonce/submission order - no extra on-chain read."""
    return "CERT-%03d" % (start_counter + index + 1)


@timed("blockchain_submit")
def submit_certificate_tx(signature: str, nonce: int):
    """B8: build + locally sign + submit via send_raw_transaction.
    Does not wait for a receipt (B2) - the caller confirms separately."""
    sender_address = _get_sender_address()
    tx = contract.functions.addCertificate(signature).build_transaction({
        "from": sender_address,
        "nonce": nonce,
        "gas": GAS_LIMIT,
    })
    signed = web3.eth.account.sign_transaction(tx, private_key=SENDER_PRIVATE_KEY)
    raw_tx = getattr(signed, "raw_transaction", None)
    if raw_tx is None:
        raw_tx = signed.rawTransaction  # older web3.py versions
    tx_hash = web3.eth.send_raw_transaction(raw_tx)
    print(f"📤 TX submitted (nonce={nonce}): {tx_hash.hex()}")
    return tx_hash


@timed("blockchain_confirm")
def wait_for_certificate_receipts(tx_hashes, timeout=300):
    """B2/B6: confirmation pass - wait for ALL receipts before the batch/request
    is considered complete (I5), using a poll latency tuned for a local
    instamine node."""
    receipts = []
    for tx_hash in tx_hashes:
        receipt = web3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=timeout, poll_latency=RECEIPT_POLL_LATENCY
        )
        receipts.append(receipt)
    print(f"✅ Confirmed {len(receipts)}/{len(tx_hashes)} transaction(s)")
    return receipts


def store_signature(signature: str) -> str:
    """Single-certificate convenience wrapper around the batch-oriented (B1/B2/
    B4b/B6/B8) primitives above - a batch of exactly one."""
    start_counter = get_certificate_counter()
    nonce = get_next_nonce()
    tx_hash = submit_certificate_tx(signature, nonce)
    wait_for_certificate_receipts([tx_hash])
    return format_certificate_id(start_counter, 0)


def get_certificate_data(certificate_id: str):
    """Read path only (untouched write semantics). B-read/V12: on-chain reads
    are cached in Redis keyed by certificate_id, since a confirmed
    certificate's signature is immutable. Only valid results are cached -
    a not-found result may just mean the write hasn't confirmed yet."""
    cache_key = f"cert:{certificate_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
            return payload["is_valid"], payload["cert_id"], payload["signature"]
    except Exception as e:
        print(f"Redis cache read error: {e}")

    try:
        is_valid, returned_id, returned_signature = contract.functions.getCertificate(certificate_id).call()
    except Exception as e:
        print(f"Blockchain read error: {e}")
        return False, "", ""

    if is_valid:
        try:
            redis_client.set(cache_key, json.dumps({
                "is_valid": is_valid,
                "cert_id": returned_id,
                "signature": returned_signature,
            }))
        except Exception as e:
            print(f"Redis cache write error: {e}")

    return is_valid, returned_id, returned_signature