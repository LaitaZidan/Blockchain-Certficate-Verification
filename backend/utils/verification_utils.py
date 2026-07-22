from celery import chain
import base64
import numpy as np
import tempfile
import os
import uuid

from utils.ocr_utils import run_ocr_and_extract, reader
from utils.hash_utils import run_hashing
from utils.rsa_utils import run_signature_check
from utils.ipfs_utils import run_regenerate_ipfs
from utils.log_utils import run_logging

from config import contract
from crypto.hash_utils import generate_md5_hash
from crypto.rsa_utils import verify_signature
from database.mongo import get_certificate_by_id
from routes.blockchain import get_certificate_data
from utils.ipfs_logic import regenerate_and_upload_ipfs
from utils.log_logic import simpan_log_verifikasi
from utils.ocr_logic import extract_text_from_image
from utils.qr_utils import extract_certificate_id_from_qr
from utils.timing import stage_timer


def process_single_certificate(image_np: np.ndarray, filename: str, username: str) -> dict:
    """Synchronous single-file verification path (V5 coarse function).

    Runs the same OCR -> hash -> RSA/chain -> decrypt/regenerate/IPFS -> log
    steps as the async 5-task chain below, as plain sequential calls, entirely
    in memory (no .npy round-trip), so /verify_certificate can return the
    decision directly instead of dispatching a background task.
    """
    durations = {}
    result = {
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

    with stage_timer(durations, "extract"):
        certificate_id = extract_certificate_id_from_qr(image_np)
        extracted = {}
        if certificate_id:
            text_lines = reader.readtext(image_np, detail=0)
            extracted = extract_text_from_image(text_lines)

    result["certificate_id"] = certificate_id
    result["step_durations"] = durations

    if not certificate_id:
        result["note"] = "QR sertifikat tidak ditemukan"
        return result

    if not extracted:
        result["note"] = "OCR gagal membaca data sertifikat"
        return result

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
    try:
        with stage_timer(durations, "blockchain"):
            chain_valid, _, signature = get_certificate_data(certificate_id)
        with stage_timer(durations, "rsa"):
            rsa_valid = bool(chain_valid) and verify_signature(hash_value, signature)
    except Exception as e:
        result["note"] = f"Verifikasi ke blockchain gagal: {e}"

    ipfs_result = {}
    if rsa_valid:
        try:
            with stage_timer(durations, "generate"):
                cert_record = get_certificate_by_id(certificate_id, contract.address)
                encrypted = cert_record.get("encrypted_data_sertif") if cert_record else None
                if encrypted:
                    ipfs_result = regenerate_and_upload_ipfs(encrypted, certificate_id)
        except Exception as e:
            result["note"] = f"Sertifikat valid, namun regenerasi sertifikat gagal: {e}"

    img_bytes = ipfs_result.get("img_bytes")
    result["valid"] = rsa_valid
    result["status"] = "success" if rsa_valid else "invalid"
    result["image_base64"] = base64.b64encode(img_bytes).decode("utf-8") if img_bytes else None
    result["ipfs_url"] = ipfs_result.get("ipfs_url")
    if not result["note"]:
        result["note"] = (
            "Sertifikat berhasil diverifikasi" if rsa_valid
            else "Tanda tangan tidak valid atau sertifikat telah diubah"
        )

    try:
        simpan_log_verifikasi(
            {
                "certificate_id": certificate_id,
                "no_sertifikat": result["no_sertifikat"],
                "hash": hash_value,
                "ipfs_cid": ipfs_result.get("ipfs_cid"),
                "ipfs_url": ipfs_result.get("ipfs_url"),
                "qr_code": ipfs_result.get("qr_code"),
                "rsa_valid": rsa_valid,
            },
            verified_by=username,
        )
    except Exception as e:
        print(f"❌ Gagal menyimpan log verifikasi: {e}")

    result["step_durations"] = durations
    return result


def jalankan_proses_verifikasi(img_np: np.ndarray, filename: str, username: str):
    # Simpan sementara sebagai .npy
    temp_dir = tempfile.gettempdir()
    unique_name = f"{uuid.uuid4().hex}_{filename.replace(' ', '_')}.npy"
    npy_path = os.path.join(temp_dir, unique_name)
    np.save(npy_path, img_np)

    # Jalankan pipeline Celery
    task_chain = chain(
        run_ocr_and_extract.s(npy_path),            
        run_hashing.s(),                  
        run_signature_check.s(),        
        run_regenerate_ipfs.s(),         
        run_logging.s()                  
    )

    task_chain.delay()

    return {
        "message": "Task verifikasi dikirim",
        "filename": filename,
        "task": unique_name
    }
