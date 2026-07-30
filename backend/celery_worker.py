import os
from celery import Celery
from kombu import Queue
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
        "utils.ipfs_utils",
        "utils.verification_utils",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # V8: dedicated queues. tasks.run_ocr_and_extract is CPU-bound OCR work
    # (V7: size that worker's --concurrency to the number of physical cores);
    # tasks.verify_certificate_coarse is the V5 coarse per-certificate
    # decision (QR/OCR/hash/RSA/chain-read, V3-overlapped internally);
    # tasks.finalize_verification_io / tasks.finalize_batch_verification_io
    # are the V9 deferred post-decision I/O (AES/regenerate/IPFS/Mongo).
    # Launch dedicated workers per queue, e.g.:
    #   celery -A celery_worker worker -Q ocr    --concurrency=<physical cores>
    #   celery -A celery_worker worker -Q verify --concurrency=<physical cores>
    #   celery -A celery_worker worker -Q io     --concurrency=<higher, I/O-bound>
    task_routes={
        "tasks.run_ocr_and_extract": {"queue": "ocr"},
        "tasks.verify_certificate_coarse": {"queue": "verify"},
        "tasks.finalize_verification_io": {"queue": "io"},
        "tasks.finalize_batch_verification_io": {"queue": "io"},
    },
    # Root cause fix: task_routes alone only controls which queue a task is
    # PUBLISHED to - it does not change which queues a worker CONSUMES from.
    # A worker started without -Q defaults to consuming only "celery", so
    # tasks routed to "ocr"/"verify"/"io" would sit unconsumed forever.
    # Declaring task_queues here makes a plain `celery worker` (no -Q needed)
    # consume from all four queues by default, while still allowing `-Q` to
    # restrict a given worker to a subset for the per-queue concurrency
    # tuning described below.
    task_queues=(
        Queue("celery"),
        Queue("ocr"),
        Queue("verify"),
        Queue("io"),
    ),
)

# Explicit imports (not just `include=[...]` above) so every task registers
# immediately regardless of how this module is loaded - `include` is only
# consumed by Celery's own worker bootstrap, not by a plain `import
# celery_worker` (e.g. from app.py or a test script).
# routes/ocr_async.py imports `run_ocr` from this module; keep that call site working.
from utils.ocr_utils import run_ocr_and_extract as run_ocr
import utils.ipfs_utils
import utils.verification_utils
