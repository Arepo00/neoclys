# Neocly AI OS SaaS (Production-Oriented Build)

## Included now
- **Auth + RBAC** (admin/client roles)
- **Tenant isolation** (per-org SQLite DB files under `data/`)
- **Client API** for seeding/running/reporting
- **Admin API** for org listing + subscription activation
- **Security basics**: password hashing (PBKDF2), bearer sessions, in-memory rate limiting, idempotency keys, audit logs
- **Frontend** with separate auth/client/admin workflows

## Run

```bash
python saas_app.py serve --host 127.0.0.1 --port 8000 --db control.db --token-secret "change-this"
```

Open `http://127.0.0.1:8000`.

## Core endpoints
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/org/report`
- `POST /api/org/seed`
- `POST /api/org/run`
- `GET /api/admin/orgs` (admin only)
- `POST /api/billing/subscribe`
- `GET /api/integrations/status`

## Test

```bash
python -m unittest -v
```


## Enterprise stack scaffold (added)
A production architecture scaffold now exists under `production/` with Docker, Postgres, Redis, Celery, FastAPI, metrics, and provider-integration entry points.

Run:
```bash
docker compose -f docker-compose.prod.yml up --build
```
