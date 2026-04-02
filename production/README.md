# Production Stack

This folder provides a production-oriented architecture scaffold:
- FastAPI app
- Postgres + Redis
- Celery worker
- Prometheus metrics endpoint
- Provider integration stubs (email/CRM/calendar/billing)

## Run locally
```bash
docker compose -f ../docker-compose.prod.yml up --build
```

## Endpoints
- `GET /health`
- `GET /readiness`
- `GET /metrics`
