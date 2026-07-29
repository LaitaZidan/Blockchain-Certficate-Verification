import base64
import concurrent.futures
import io
import numpy as np
from celery import shared_task, group
from PIL import Image

from config import contract
from crypto.hash_utils import generate_md5_hash
from crypto.rsa_utils import verify_signature
from database.mongo import get_certificate_by_id
from routes.blockchain import get_certificate_data
from utils.ipfs_logic import decrypt_and_regenerate
from utils.ipfs_utils import finalize_verification_io, finalize_batch_verification_io
from utils.log_logic import simpan_log_verifikasi
from utils.ocr_logic import extract_fields_from_rois, signed_fields_present
from utils.qr_utils import extract_certificate_id_from_qr
from utils.timing import stage_timer


def _empty_result():
    return {
        "status": "invalid",
        "valid": False,
        "certificate_id": None,
        "no_sertifikat": None,
        "name": None,
        "student_id": None,
        "department": None,
        "test_date": None,
        "hash": None,
        "image_base64": None,
        "ipfs_url": None,
        "note": "",
    }


def _decide(image_np: np.ndarray):
    """QR decode, then V3: overlap OCR, the on-chain signature fetch, and the
    encrypted-record fetch (needed later for decrypt/regenerate) within this
    one certificate, as plain function calls on a thread pool (V5) rather
    than separate chained Celery tasks.

    Returns (result_dict, cert_record_or_None). `result_dict["status"]` is
    "success"/"invalid" once a decision was reached, or left as "invalid"
    with a note if verification couldn't proceed (no QR / OCR failure /
    chain read failure).
    """
    durations = {}
    result = _empty_result()

    certificate_id = extract_certificate_id_from_qr(image_np)
    result["certificate_id"] = certificate_id
    if not certificate_id:
        result["note"] = "QR sertifikat tidak ditemukan"
        result["step_durations"] = durations
        return result, None

    def _ocr():
        with stage_timer(durations, "extract"):
            return extract_fields_from_rois(image_np)

    def _chain_read():
        with stage_timer(durations, "blockchain"):
            return get_certificate_data(certificate_id)

    def _mongo_read():
        return get_certificate_by_id(certificate_id, contract.address)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        ocr_future = executor.submit(_ocr)
        chain_future = executor.submit(_chain_read)
        mongo_future = executor.submit(_mongo_read)

        extracted = ocr_future.result()
        if not signed_fields_present(extracted):
            extracted = {}

        try:
            chain_valid, _, signature = chain_future.result()
        except Exception as e:
            chain_valid, signature = False, None
            result["note"] = f"Verifikasi ke blockchain gagal: {e}"

        cert_record = mongo_future.result()

    result["step_durations"] = durations

    if not extracted:
        result["note"] = result["note"] or "OCR gagal membaca data sertifikat"
        return result, cert_record

    result.update({
        "no_sertifikat": extracted.get("no_sertifikat"),
        "name": extracted.get("name"),
        "student_id": extracted.get("student_id"),
        "department": extracted.get("department"),
        "test_date": extracted.get("test_date"),
    })

    hash_value = generate_md5_hash(
        f"{extracted.get('no_sertifikat')}|{extracted.get('name')}|{extracted.get('student_id')}"
    )
    result["hash"] = hash_value

    rsa_valid = False
    if not result["note"]:
        try:
            with stage_timer(durations, "rsa"):
                rsa_valid = bool(chain_valid) and verify_signature(hash_value, signature)
        except Exception as e:
            result["note"] = f"Verifikasi ke blockchain gagal: {e}"

    result["valid"] = rsa_valid
    result["status"] = "success" if rsa_valid else "invalid"
    if not result["note"]:
        result["note"] = (
            "Sertifikat berhasil diverifikasi" if rsa_valid
            else "Tanda tangan tidak valid atau sertifikat telah diubah"
        )
    result["step_durations"] = durations
    return result, cert_record


def process_single_certificate(image_np: np.ndarray, filename: str, username: str) -> dict:
    """Synchronous single-file verification path (V5). Decision, OCR fields,
    and the regenerated image are all ready before this returns. V9: only the
    IPFS upload (and filling it into the already-written verify log) is
    deferred off the critical path.
    """
    result, cert_record = _decide(image_np)
    certificate_id = result.get("certificate_id")

    if not certificate_id or not result["hash"]:
        return result

    encrypted = cert_record.get("encrypted_data_sertif") if cert_record else None
    img_bytes = None
    if result["valid"] and encrypted:
        try:
            with stage_timer(result["step_durations"], "generate"):
                regenerated = decrypt_and_regenerate(encrypted, certificate_id)
            img_bytes = regenerated["img_bytes"]
            result["image_base64"] = regenerated["img_base64"]
        except Exception as e:
            result["note"] = f"Sertifikat valid, namun regenerasi sertifikat gagal: {e}"

    try:
        simpan_log_verifikasi(
            {
                "certificate_id": certificate_id,
                "no_sertifikat": result["no_sertifikat"],
                "hash": result["hash"],
                "ipfs_cid": None,
                "ipfs_url": None,
                "qr_code": None,
                "rsa_valid": result["valid"],
            },
            verified_by=username,
        )
    except Exception as e:
        print(f"❌ Gagal menyimpan log verifikasi: {e}")

    # V9: resolve the IPFS CID asynchronously; /api/verify/<certificate_id>
    # picks it up once finalize_verification_io updates the log above. A
    # broker outage must not turn an already-made decision into a failure -
    # the decision and regenerated image are already final at this point.
    if result["valid"] and img_bytes:
        try:
            finalize_verification_io.delay(
                certificate_id, base64.b64encode(img_bytes).decode("utf-8"), update_existing=True
            )
        except Exception as e:
            print(f"⚠️ Gagal menjadwalkan upload IPFS async: {e}")

    return result


@shared_task(name="tasks.verify_certificate_coarse")
def verify_certificate_task(image_base64: str, filename: str, username: str):
    """V5: the coarse per-certificate verification task - one Celery task
    instead of the old 5-task chain, with V3's overlap and the decision logic
    as plain function calls. V6 dispatches these as a group for batch
    verification. V9: for batch, all post-decision I/O is fully async, so
    this task only makes the decision and hands the rest to a deferred task.
    """
    image_np = np.array(Image.open(io.BytesIO(base64.b64decode(image_base64))).convert("RGB"))
    result, cert_record = _decide(image_np)
    certificate_id = result.get("certificate_id")

    if certificate_id and result["hash"]:
        encrypted = cert_record.get("encrypted_data_sertif") if cert_record else None
        try:
            finalize_batch_verification_io.delay(
                certificate_id,
                encrypted,
                result["hash"],
                result["no_sertifikat"],
                result["valid"],
                username,
            )
        except Exception as e:
            print(f"⚠️ Gagal menjadwalkan post-decision I/O batch: {e}")

    return {
        "file": filename,
        "certificate_id": certificate_id,
        "status": result["status"],
        "valid": result["valid"],
        "note": result["note"],
    }


def jalankan_proses_verifikasi_batch(files: list, username: str) -> dict:
    """V6: batch verification dispatches the coarse per-certificate task as a
    Celery group, instead of one 5-task chain per file. `files` is a list of
    (filename, image_bytes) tuples.
    """
    tasks = [
        verify_certificate_task.s(base64.b64encode(image_bytes).decode("utf-8"), filename, username)
        for filename, image_bytes in files
    ]
    group(tasks).apply_async()
    return {
        "message": "Task verifikasi dikirim",
        "total_files": len(files),
    }
