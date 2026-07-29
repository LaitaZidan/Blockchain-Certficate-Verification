import numpy as np
import os
from celery import shared_task
from utils.qr_utils import extract_certificate_id_from_qr
from utils.ocr_logic import extract_fields_from_rois, signed_fields_present

@shared_task(name="tasks.run_ocr_and_extract")
def run_ocr_and_extract(file_path):
    try:
        img_np = np.load(file_path)
        certificate_id = extract_certificate_id_from_qr(img_np)

        if not certificate_id:
            return {"status": "QR tidak ditemukan"}

        extracted = extract_fields_from_rois(img_np)

        os.remove(file_path)  # cleanup

        if not signed_fields_present(extracted):
            return {"certificate_id": certificate_id, "status": "OCR gagal"}

        return {
            "status": "ok",
            "certificate_id": certificate_id,
            "extracted": extracted
        }

    except Exception as e:
        return {"status": f"error: {str(e)}"}
