
import base64
import io
import os
import qrcode
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from utils.layout import TEMPLATE_PATH, FIELD_ANCHORS, QR_POSITION, QR_SIZE, FONT_PATH, FONT_SIZE

# G1: template loaded/decoded once at import; copy() per certificate below.
if not os.path.exists(TEMPLATE_PATH):
    raise FileNotFoundError("Template sertifikat tidak ditemukan")
_TEMPLATE_IMAGE = Image.open(TEMPLATE_PATH).convert("RGBA")

# G2: font object loaded once at import.
try:
    _FONT_DEFAULT = ImageFont.truetype(FONT_PATH, FONT_SIZE)
except Exception:
    _FONT_DEFAULT = ImageFont.load_default()

# Regenerate sertifikat terverifikasi
def regenerate_verified_certificate(data, certificate_id):
    # G1: reuse the template loaded once at import.
    img = _TEMPLATE_IMAGE.copy()
    draw = ImageDraw.Draw(img)

    # G2: reuse the font object loaded once at import.
    font = _FONT_DEFAULT

    # 🖊️ Tulis ulang seluruh data ke template (G5: anchors from the shared layout module)
    draw.text(FIELD_ANCHORS["no_sertifikat"], data["no_sertifikat"], font=font, fill="black")
    draw.text(FIELD_ANCHORS["name"], data["name"], font=font, fill="black")
    draw.text(FIELD_ANCHORS["student_id"], data["student_id"], font=font, fill="black")
    draw.text(FIELD_ANCHORS["department"], data["department"], font=font, fill="black")
    draw.text(FIELD_ANCHORS["test_date"], data["test_date"], font=font, fill="black")

    draw.text(FIELD_ANCHORS["listening"], str(data["listening"]), font=font, fill="black")
    draw.text(FIELD_ANCHORS["reading"], str(data["reading"]), font=font, fill="black")
    draw.text(FIELD_ANCHORS["total_lr"], str(data["total_lr"]), font=font, fill="black")
    draw.text(FIELD_ANCHORS["writing"], str(data["writing"]), font=font, fill="black")
    draw.text(FIELD_ANCHORS["total_writing"], str(data["total_writing"]), font=font, fill="black")

    # Generate QR final → link publik
    qr_data = f"https://localhost:5173/verify/{certificate_id}"
    qr_img = qrcode.make(qr_data).convert("RGBA").resize(QR_SIZE)

    # G4: vectorized transparent QR (replaces the per-pixel Python loop;
    # output pixels are identical: white -> alpha 0, everything else untouched).
    qr_arr = np.array(qr_img)
    white_mask = np.all(qr_arr[:, :, :3] == 255, axis=-1)
    qr_arr[white_mask, 3] = 0
    qr_img = Image.fromarray(qr_arr, mode="RGBA")

    img.paste(qr_img, QR_POSITION, qr_img)

    # Tambahkan tanda tangan
    try:
        ttd_img = Image.open("static/ttd.png").convert("RGBA").resize((250, 100))
        img.paste(ttd_img, (350, 1140), ttd_img)
        img.paste(ttd_img, (1400, 1140), ttd_img)
    except Exception as e:
        print("⚠️ Gagal pasang tanda tangan:", e)

    # Simpan image ke buffer dan encode base64
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_bytes = buffer.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
    

    # QR juga ke base64 untuk disimpan
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_base64 = base64.b64encode(qr_buffer.getvalue()).decode("utf-8")

    return img_bytes, img_base64, qr_base64