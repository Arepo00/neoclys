import os
from fastapi import FastAPI
from prometheus_client import Counter, generate_latest
from fastapi.responses import PlainTextResponse

REQUESTS = Counter("neocly_api_requests_total", "Total API Requests", ["path"])

app = FastAPI(title="Neocly Production API")


@app.middleware("http")
async def metrics_mw(request, call_next):
    REQUESTS.labels(path=request.url.path).inc()
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True, "env": os.getenv("ENV", "dev")}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode(), media_type="text/plain; version=0.0.4")


@app.get("/readiness")
def readiness():
    return {
        "postgres": "configured" if os.getenv("DATABASE_URL") else "missing",
        "redis": "configured" if os.getenv("REDIS_URL") else "missing",
        "celery": "configured" if os.getenv("CELERY_BROKER_URL") else "missing",
        "providers": {
            "email": bool(os.getenv("SENDGRID_API_KEY")),
            "crm": bool(os.getenv("HUBSPOT_API_KEY")),
            "billing": bool(os.getenv("STRIPE_API_KEY")),
        },
    }
