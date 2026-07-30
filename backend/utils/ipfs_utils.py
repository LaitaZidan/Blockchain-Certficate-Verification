# ipfs_utils.py
import base64
from celery import shared_task
from utils.ipfs_logic import decrypt_and_regenerate, upload_regenerated_to_ipfs
from database.mongo import update_verify_log_ipfs, save_verify_log
from config import contract


@shared_task(name="tasks.finalize_verification_io")
def finalize_verification_io(certificate_id, img_base64, update_existing=True):
    """V9: IPFS upload runs after the decision, off the critical path.

    update_existing=True (single-verification path): the verify log for this
    certificate was already written synchronously (image already regenerated
    for the response); this task only fills in ipfs_cid/ipfs_url once the
    upload completes, via the existing /api/verify/<certificate_id> lookup.
    """
    try:
        img_bytes = base64.b64decode(img_base64)
        ipfs = upload_regenerated_to_ipfs(img_bytes)
        if update_existing:
            update_verify_log_ipfs(certificate_id, ipfs.get("cid"), ipfs.get("url"))
        return {"status": "ok", "certificate_id": certificate_id, "ipfs_cid": ipfs.get("cid"), "ipfs_url": ipfs.get("url")}
    except Exception as e:
        return {"status": f"error: {e}", "certificate_id": certificate_id}


@shared_task(name="tasks.finalize_batch_verification_io")
def finalize_batch_verification_io(certificate_id, encrypted_data_sertif, hash_value, no_sertifikat, rsa_valid, username):
    """V9: for batch verification, all post-decision I/O (decrypt, regenerate,
    IPFS upload, verify-log write) is fully async - this task is that entire
    remainder, dispatched only for certificates whose decision was already
    made by the coarse task (see verification_utils.verify_certificate_task).
    """
    ipfs_cid = None
    ipfs_url = None
    qr_code = None
    try:
        if rsa_valid and encrypted_data_sertif:
            regenerated = decrypt_and_regenerate(encrypted_data_sertif, certificate_id)
            qr_code = regenerated.get("qr_code")
            ipfs = upload_regenerated_to_ipfs(regenerated["img_bytes"])
            ipfs_cid = ipfs.get("cid")
            ipfs_url = ipfs.get("url")
    except Exception as e:
        print(f"⚠️ Batch post-decision I/O gagal untuk {certificate_id}: {e}")

    try:
        save_verify_log({
            "certificate_id": certificate_id,
            "no_sertifikat": no_sertifikat,
            "contract_address": contract.address,
            "ipfs_cid": ipfs_cid,
            "ipfs_url": ipfs_url,
            "qr_code": qr_code,
            "hash": hash_value,
            "verified_by": username,
            "valid": rsa_valid,
            "result": "success" if rsa_valid else "failed",
            "note": "Sertifikat berhasil diverifikasi" if rsa_valid else "Verifikasi gagal",
        })
    except Exception as e:
        print(f"❌ Gagal menyimpan log verifikasi batch: {e}")

    return {"certificate_id": certificate_id, "ipfs_cid": ipfs_cid, "ipfs_url": ipfs_url}
