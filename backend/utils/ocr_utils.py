import numpy as np
import easyocr
import os
from celery import shared_task
from utils.qr_utils import extract_certificate_id_from_qr
from utils.ocr_logic import extract_text_from_image  # dipisah logika ekstrak OCR agar modular

reader = easyocr.Reader(["en", "id"], gpu=True)

@shared_task(name="tasks.run_ocr_and_extract")
def run_ocr_and_extract(file_path):
    try:
        img_np = np.load(file_path)
        certificate_id = extract_certificate_id_from_qr(img_np)

        if not certificate_id:
            return {"status": "QR tidak ditemukan"}

        text_lines = reader.readtext(img_np, detail=0)
        extracted = extract_text_from_image(text_lines)

        os.remove(file_path)  # cleanup

        if not extracted:
            return {"certificate_id": certificate_id, "status": "OCR gagal"}

        return {
            "status": "ok",
            "certificate_id": certificate_id,
            "ocr_result": text_lines,
            "extracted": extracted
        }

    except Exception as e:
        return {"status": f"error: {str(e)}"}
