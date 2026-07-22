from flask import Blueprint, request, jsonify, send_file, session
import io
import base64
import os
import contextlib
import multiprocessing
import concurrent.futures
import qrcode
import numpy as np
import pandas as pd
import shutil
import zipfile
from PIL import ImageFont
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from config import contract, AES_SECRET_KEY
from database.mongo import (
    save_certificate_data,
    build_certificate_document,
    save_certificates_bulk,
    get_certificate_by_id,
    collection_cert,
)
from crypto.hash_utils import generate_md5_hash
from crypto.rsa_utils import load_private_key, sign_data
from crypto.aes_utils import encrypt_data
from routes.blockchain import store_signature
from database.auth import get_fingerprint
from utils.timing import timed
from utils.layout import TEMPLATE_PATH, FIELD_ANCHORS, QR_POSITION, QR_SIZE, FONT_PATH, FONT_SIZE

certificate_bp = Blueprint("certificate", __name__)

# G6: serializes only the blockchain submit-wait-read-counter section (store_signature)
# across worker processes, so certificate_id assignment (still read from the global
# on-chain counter, unchanged from Sprint 0/1) can't race under parallel batch
# generation. Everything else in generate_certificate runs fully in parallel.
# Defaults to a no-op for the single-certificate path, where there's no pool.
_blockchain_lock = contextlib.nullcontext()

def _init_batch_worker(lock):
    global _blockchain_lock
    _blockchain_lock = lock

# G1: template loaded/decoded once at import; copy() per certificate below.
if not os.path.exists(TEMPLATE_PATH):
    raise FileNotFoundError("Template sertifikat tidak ditemukan")
_TEMPLATE_IMAGE = Image.open(TEMPLATE_PATH)

# G2: font object loaded once at import.
try:
    _FONT_DEFAULT = ImageFont.truetype(FONT_PATH, FONT_SIZE)
except IOError:
    _FONT_DEFAULT = ImageFont.load_default()

# Fungsi untuk format tanggal
def format_date(date_str):
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%d %B %Y")
    except ValueError:
        return date_str

# Fungsi untuk mengambil certificate ID terbaru dari blockchain
def get_certificate_id_from_blockchain():
    return contract.functions.certificateCounter().call()

@timed("generation")
def generate_certificate(data, save_to_db=True):
    # Validasi input
    required_fields = [
        "no_sertifikat", "name", "student_id", "department", "test_date",
        "listening", "reading", "writing", "total_lr", "total_writing"
    ]
    for field in required_fields:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")
    # Konversi tipe field sesuai definisi frontend
    try:
        data["listening"] = int(data["listening"])
        data["reading"] = int(data["reading"])
        data["writing"] = int(data["writing"])
        data["total_lr"] = int(data["total_lr"])
        data["total_writing"] = int(data["total_writing"])
    except (ValueError, TypeError):
        raise ValueError("Field nilai Listening, Reading, Writing, Total LR, dan Total Writing harus berupa angka (integer).")

    # Konversi semua field lainnya jadi string agar aman untuk hash dan proses lainnya
    for key in data:
        if key not in ["listening", "reading", "writing", "total_lr", "total_writing"]:
            if not isinstance(data[key], str):
                data[key] = str(data[key])

    # Format hash input
    hash_input = f"{data['no_sertifikat']}|{data['name']}|{data['student_id']}"
    print("📌 HASH input saat generate:", hash_input)
    md5_hash = generate_md5_hash(hash_input)



    # Digital signature
    private_key = load_private_key()
    signature = sign_data(md5_hash, private_key)

    # Enkripsi data user
    user_info = {
        **{k: data[k] for k in required_fields},
    }
    encrypted_info = encrypt_data(user_info, AES_SECRET_KEY)

    # Transaksi ke blockchain
    with _blockchain_lock:
        certificate_id = store_signature(signature)
    contract_address = contract.address

    # Buat QR code
    qr_data = f"https://127.0.0.1:5000/verify?certificate_id={certificate_id}"
    qr_img = qrcode.make(qr_data).convert("RGBA").resize(QR_SIZE)
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_base64 = base64.b64encode(qr_buffer.getvalue()).decode()

    # G4: vectorized transparent QR (replaces the per-pixel Python loop;
    # output pixels are identical: white -> alpha 0, everything else untouched).
    qr_arr = np.array(qr_img)
    white_mask = np.all(qr_arr[:, :, :3] == 255, axis=-1)
    qr_arr[white_mask, 3] = 0
    qr_img = Image.fromarray(qr_arr, mode="RGBA")

    # G1: reuse the template loaded once at import.
    img = _TEMPLATE_IMAGE.copy()
    draw = ImageDraw.Draw(img)

    # G2: reuse the font object loaded once at import.
    font_default = _FONT_DEFAULT

    # Insert data ke posisi yang sesuai (G5: anchors from the shared layout module)
    draw.text(FIELD_ANCHORS["no_sertifikat"], data["no_sertifikat"], font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["name"], data["name"], font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["student_id"], data["student_id"], font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["department"], data["department"], font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["test_date"], data["test_date"], font=font_default, fill="black")

    draw.text(FIELD_ANCHORS["listening"], str(data["listening"]), font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["reading"], str(data["reading"]), font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["total_lr"], str(data["total_lr"]), font=font_default, fill="black")

    draw.text(FIELD_ANCHORS["writing"], str(data["writing"]), font=font_default, fill="black")
    draw.text(FIELD_ANCHORS["total_writing"], str(data["total_writing"]), font=font_default, fill="black")

    img.paste(qr_img, QR_POSITION, qr_img)

    # Simpan hasil sertifikat ke buffer base64
    cert_buffer = io.BytesIO()
    img.save(cert_buffer, format="PNG")
    cert_base64 = base64.b64encode(cert_buffer.getvalue()).decode()

    # G8: build the document and hand the image back in-process; the caller
    # (single-generate vs batch) decides how it gets persisted.
    document = build_certificate_document(
        certificate_id=certificate_id,
        contract_address=contract_address,
        encrypted_data_sertif=encrypted_info,
        qr_base64=qr_base64,
        cert_base64=cert_base64
    )

    if save_to_db:
        save_certificate_data(
            certificate_id=certificate_id,
            contract_address=contract_address,
            encrypted_data_sertif=encrypted_info,
            qr_base64=qr_base64,
            cert_base64=cert_base64
        )

    return certificate_id, cert_base64, document


@certificate_bp.route("/generate_certificate", methods=["POST"])
def generate():
    # Validasi session fingerprint
    expected_fingerprint = session.get("fingerprint")
    current_fingerprint = get_fingerprint()

    if expected_fingerprint != current_fingerprint:
        session.clear()
        return jsonify({"error": "Session mismatch"}), 401

    # Validasi role
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        data = request.get_json()
        certificate_id, _cert_base64, _document = generate_certificate(data)
        return jsonify({
            "message": "Certificate generated successfully",
            "certificate_id": certificate_id,
            "download_url": f"/certificate/download_certificate/{certificate_id}"
        }), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@certificate_bp.route("/upload_excel", methods=["POST"])
def upload_excel_and_download_zip():
    expected_fingerprint = session.get("fingerprint")
    current_fingerprint = get_fingerprint()

    if expected_fingerprint != current_fingerprint:
        session.clear()
        return jsonify({"error": "Session mismatch"}), 401

    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    filename = file.filename
    try:
        # Baca file berdasarkan extension
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(file)
        elif filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            return jsonify({"error": "Format file tidak didukung. Hanya .xlsx, .xls, .csv"}), 400
    except Exception as e:
        return jsonify({"error": f"Gagal membaca file: {str(e)}"}), 400
    
    if len(df) > 100:
        return jsonify({"error": "Maksimal 100 data per upload untuk mencegah overload server."}), 400

    required_columns = ["no_sertifikat", "name", "student_id", "department", "test_date", "listening", "reading", "writing", "total_lr", "total_writing"]
    for col in required_columns:
        if col not in df.columns:
            return jsonify({"error": f"Missing column: {col}"}), 400

    rows = [row.to_dict() for _, row in df.iterrows()]

    # G6: parallelize batch generation across CPU cores. Each worker runs the
    # full per-certificate pipeline (render + hash + sign + encrypt) and does
    # NOT write to Mongo itself (save_to_db=False) - G7 does one bulk write
    # below instead. "spawn" is forced explicitly so worker start-up behaves
    # identically on macOS and Linux.
    generated_ids = []
    documents = []
    zip_entries = []

    max_workers = min(len(rows), os.cpu_count() or 1) or 1
    mp_context = multiprocessing.get_context("spawn")
    lock = mp_context.Lock()

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=mp_context,
        initializer=_init_batch_worker,
        initargs=(lock,),
    ) as executor:
        future_to_row = {
            executor.submit(generate_certificate, row, save_to_db=False): row
            for row in rows
        }
        for future in concurrent.futures.as_completed(future_to_row):
            row = future_to_row[future]
            try:
                certificate_id, cert_base64, document = future.result()
                generated_ids.append(certificate_id)
                documents.append(document)
                zip_entries.append((certificate_id, base64.b64decode(cert_base64)))
            except Exception as e:
                print(f"Gagal generate untuk {row.get('name')}: {e}")

    if not generated_ids:
        return jsonify({"error": "Tidak ada sertifikat berhasil dibuat"}), 500

    # G7: single bulk write for the whole batch instead of one upsert per certificate.
    save_certificates_bulk(documents)

    # G9: build the ZIP in memory instead of writing per-file PNGs to a temp directory.
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zipf:
        for certificate_id, png_bytes in zip_entries:
            zipf.writestr(f"{certificate_id}.png", png_bytes)
    zip_buffer.seek(0)

    # Kirim ZIP sebagai download
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="all_certificates.zip"
    )
    
@certificate_bp.route("/download_certificate/<certificate_id>", methods=["GET"])
def download_certificate(certificate_id):
    # Cek fingerprint
    if session.get("fingerprint") != get_fingerprint():
        session.clear()
        return jsonify({"error": "Session mismatch"}), 401

    # Cek role admin
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    
    contract_address = contract.address 
    record = get_certificate_by_id(certificate_id, contract_address)

    if not record:
        return jsonify({"error": "Certificate not found"}), 404

    cert_b64 = record.get("certificate_png")
    if not cert_b64:
        return jsonify({"error": "Certificate image not stored"}), 404

    cert_binary = base64.b64decode(cert_b64)
    return send_file(
        io.BytesIO(cert_binary),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"{certificate_id}.png"
    )

@certificate_bp.route("/download_batch_zip", methods=["GET"])
def download_batch_zip():
    expected_fingerprint = session.get("fingerprint")
    current_fingerprint = get_fingerprint()

    if expected_fingerprint != current_fingerprint:
        session.clear()
        return jsonify({"error": "Session mismatch"}), 401

    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Ambil semua sertifikat dari MongoDB
        all_certificates = list(collection_cert.find())

        if not all_certificates:
            return jsonify({"error": "Tidak ada sertifikat ditemukan di database"}), 404

        # Siapkan folder temp
        temp_folder = "temp_batch_certificates"
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)
        os.makedirs(temp_folder)

        # Simpan semua PNG dari database
        for cert in all_certificates:
            certificate_id = cert.get("certificate_id")
            cert_b64 = cert.get("certificate_png")
            if not certificate_id or not cert_b64:
                continue

            cert_binary = base64.b64decode(cert_b64)
            output_path = os.path.join(temp_folder, f"{certificate_id}.png")
            with open(output_path, "wb") as f_out:
                f_out.write(cert_binary)

        # Buat ZIP
        zip_path = "batch_certificates.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for filename in os.listdir(temp_folder):
                file_path = os.path.join(temp_folder, filename)
                zipf.write(file_path, filename)

        # Bersihkan folder temp
        shutil.rmtree(temp_folder)

        # Return ZIP
        return send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name="batch_certificates.zip"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500