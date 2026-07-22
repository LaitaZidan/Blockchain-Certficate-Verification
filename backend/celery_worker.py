import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery = Celery(
    "certificate_verification",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "utils.ocr_utils",
        "utils.hash_utils",
        "utils.rsa_utils",
        "utils.ipfs_utils",
        "utils.log_utils",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)

# routes/ocr_async.py imports `run_ocr` from this module; keep that call site working.
from utils.ocr_utils import run_ocr_and_extract as run_ocr
