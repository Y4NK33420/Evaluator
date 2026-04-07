"""Celery application — two queues, one broker."""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "amgs",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.ocr_tasks",
        "app.workers.grading_tasks",
        "app.workers.code_eval_tasks",
        "app.workers.code_eval_env_tasks",
    ],
)

celery_app.conf.update(
    task_serializer      = "json",
    result_serializer    = "json",
    accept_content       = ["json"],
    timezone             = "UTC",
    enable_utc           = True,
    task_track_started   = True,
    task_acks_late       = True,   # re-queue if worker crashes mid-task
    worker_prefetch_multiplier = 1,  # one task at a time per worker slot

    task_routes = {
        "app.workers.ocr_tasks.*":     {"queue": "ocr_queue"},
        "app.workers.grading_tasks.*": {"queue": "grading_queue"},
        "app.workers.code_eval_tasks.*": {"queue": "code_eval_queue"},
        "app.workers.code_eval_env_tasks.*": {"queue": "code_eval_queue"},
    },

    # OCR queue: strictly sequential (GPU-bound)
    # Run a dedicated worker: celery -A app.workers.celery_app worker -Q ocr_queue -c 1
    #
    # Grading queue: concurrent (I/O-bound Gemini calls)
    # Run a dedicated worker: celery -A app.workers.celery_app worker -Q grading_queue -c 8
    #
    # Code-eval queue: isolated execution lifecycle lane
    # Run a dedicated worker: celery -A app.workers.celery_app worker -Q code_eval_queue -c 2
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.workers"])
