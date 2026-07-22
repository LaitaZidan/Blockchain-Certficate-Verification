import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "static")

# Single source of the certificate template path. The on-disk file is
# "PECT_template.png" (mixed case) — the previous "pect_template.png"
# reference in certificate.py/image_logic.py only worked on case-insensitive
# filesystems.
TEMPLATE_PATH = os.path.join(STATIC_DIR, "PECT_template.png")

FONT_DIR = os.path.join(STATIC_DIR, "font")
FONT_PATH = os.path.join(FONT_DIR, "Montserrat-SemiBold.ttf")
FONT_SIZE = 25

# Single source of field anchor coordinates for both certificate drawing
# (generation + regeneration) and verification ROI cropping (V1, Sprint 4).
# no_sertifikat | name | student_id are the frozen signed fields.
FIELD_ANCHORS = {
    "no_sertifikat": (1005, 454),
    "name": (415, 502),
    "student_id": (415, 536),
    "department": (1225, 502),
    "test_date": (1225, 536),
    "listening": (640, 655),
    "reading": (980, 655),
    "total_lr": (1310, 655),
    "writing": (830, 948),
    "total_writing": (1130, 948),
}

QR_POSITION = (880, 1090)
QR_SIZE = (200, 200)
