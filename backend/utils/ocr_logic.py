import cv2
import numpy as np
import pytesseract
from PIL import Image

from utils.layout import FIELD_ROI_BOXES, SIGNED_FIELDS

# V2: Tesseract (LSTM engine), single-line mode, recognition-only.
TESSERACT_CONFIG = "--oem 1 --psm 7"

# V4: upscale target for the recognizer's preferred text height. Rendered
# field text is ~20-25px tall; Tesseract's LSTM model performs best well
# above that, so crops are upscaled before recognition.
TARGET_HEIGHT = 90


def preprocess_roi(crop: Image.Image) -> Image.Image:
    """V4: grayscale, mild Otsu binarization, upscale to the recognizer's
    preferred height. This can only make a crop harder to read correctly -
    never fabricate matching text - so it stays fail-safe (I3): a misread
    still changes the hash and causes a verification failure, never a false
    accept.
    """
    gray = np.array(crop.convert("L"))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary_img = Image.fromarray(binary)

    if binary_img.height and binary_img.height < TARGET_HEIGHT:
        scale = TARGET_HEIGHT / binary_img.height
        new_width = max(1, round(binary_img.width * scale))
        binary_img = binary_img.resize((new_width, TARGET_HEIGHT), Image.LANCZOS)

    return binary_img


def recognize_field(crop: Image.Image) -> str:
    """V2: Tesseract (LSTM), single-line, recognition-only on one ROI crop."""
    return pytesseract.image_to_string(crop, config=TESSERACT_CONFIG).strip()


def extract_fields_from_rois(image_np: np.ndarray) -> dict:
    """V1: crop only the known signed-field (+ display-only) boxes from the
    shared layout module and OCR just those crops - no full-image OCR, no
    text detection/label search. Returns one string per field ("" if that
    field couldn't be read); the caller decides what counts as usable
    (see signed_fields_present) - this never substitutes a passing value for
    an unreadable field (I3).
    """
    img = Image.fromarray(image_np)
    extracted = {}
    for field, box in FIELD_ROI_BOXES.items():
        try:
            crop = img.crop(box)
            processed = preprocess_roi(crop)
            extracted[field] = recognize_field(processed)
        except Exception as e:
            print(f"⚠️ OCR gagal untuk field '{field}': {e}")
            extracted[field] = ""

    print("📌 Ekstrak OCR (ROI):", extracted)
    return extracted


MIN_FIELD_LENGTH = 3  # filters out short Tesseract hallucinations on near-blank crops


def signed_fields_present(extracted: dict) -> bool:
    """I2: OCR must cover every signed field; any missing/empty/too-short one
    means the read is unusable and must be treated as a verification failure.
    This is a plausibility pre-filter only, not the security decision -
    RSA verification against the (possibly-garbage) OCR hash is what
    actually enforces I1/I3/I4 either way."""
    return all(
        len((extracted.get(field) or "").strip()) >= MIN_FIELD_LENGTH
        for field in SIGNED_FIELDS
    )
