import os
from celery import Celery

celery_app = Celery(
    "neocly",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)


@celery_app.task(name="jobs.process_outbound")
def process_outbound(org_id: int, payload: dict) -> dict:
    return {"org_id": org_id, "task": "outbound", "payload": payload, "status": "processed"}


@celery_app.task(name="jobs.process_sales")
def process_sales(org_id: int, payload: dict) -> dict:
    return {"org_id": org_id, "task": "sales", "payload": payload, "status": "processed"}
