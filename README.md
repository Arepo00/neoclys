# Neocly AI OS SaaS

A full-stack SaaS starter for Neocly AI OS with:
- Backend API + automation engine (Python + SQLite)
- Frontend dashboard (HTML/CSS/JS)
- Autonomous outbound + sales + F2A loop

## Run as SaaS (web app)

```bash
python neocly_os.py --db neocly_os.db serve --host 127.0.0.1 --port 8080
```

Then open: `http://127.0.0.1:8080`

From the dashboard you can:
1. Initialize system
2. Seed leads
3. Run automation days
4. View live KPI report
5. Run full verification checklist

## CLI mode

```bash
python neocly_os.py --db neocly_os.db init
python neocly_os.py --db neocly_os.db seed-leads 3000
python neocly_os.py --db neocly_os.db run 60
python neocly_os.py --db neocly_os.db report
python neocly_os.py --db neocly_os.db verify
```

## Windows fixes included
- Replaced deprecated `datetime.utcnow()` with timezone-aware `datetime.now(dt.timezone.utc)`.
- Added explicit DB connection close via context manager to avoid SQLite file locks during test temp directory cleanup.

## Test

```bash
python -m unittest -v
```
