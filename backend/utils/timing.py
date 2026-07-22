import functools
import json
import os
import time
from contextlib import contextmanager

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(os.path.dirname(BASE_DIR), "logs")
LOG_PATH = os.path.join(LOG_DIR, "timing.log")


def record_stage(stage: str, duration_seconds: float, **meta):
    """Append one timing sample to the M1 measurement log. Never raises."""
    entry = {
        "stage": stage,
        "duration_seconds": round(duration_seconds, 6),
        "timestamp": time.time(),
        **meta,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


@contextmanager
def stage_timer(durations: dict, stage: str, **meta):
    """Time a block, record it into `durations[stage]`, and log it via record_stage."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        durations[stage] = round(elapsed, 6)
        record_stage(stage, elapsed, **meta)


def timed(stage: str):
    """Decorator form of stage_timer for functions whose signature/return must stay unchanged."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                record_stage(stage, time.perf_counter() - start)
        return wrapper
    return decorator
