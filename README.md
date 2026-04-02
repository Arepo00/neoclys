# Neocly AI OS (Functional System)

This repository provides a runnable autonomous acquisition + sales operating system with a self-improving F2A loop.

## What is implemented

### 1) AI Outbound System
- Sends outreach daily to new leads (`daily_outreach_capacity`).
- Tracks replies, bookings, and **qualified bookings** per message.
- Rebalances templates automatically from performance data.

### 2) AI Sales OS
- Processes booked qualified calls into show-up/win/revenue outcomes.
- Learns on **every call** (playbook quality + routing weight updates).
- Improves close rate over time from observed conversion data.

### 3) AI F2A Loop (Feedback → Action)
- Reads acquisition and sales data from SQLite tables.
- Detects bottlenecks (template variance, close-rate leakage).
- Writes automatic optimization actions to `f2a_actions`.

## Quick start


## Fastest way to run

```bash
./run_demo.sh
```

Optional args:

```bash
./run_demo.sh my_system.db 19
```

What it does:
1. Initializes SQLite DB
2. Seeds 3000 leads
3. Runs 60 simulated days
4. Prints report
5. Runs full checkbox verification


```bash
python neocly_os.py --db neocly_os.db init
python neocly_os.py --db neocly_os.db seed-leads 3000
python neocly_os.py --db neocly_os.db run 60
python neocly_os.py --db neocly_os.db report
```

## Full checkbox verification

Run the built-in verifier (60-day run + pass/fail checklist):

```bash
python neocly_os.py --db verify.db --seed 19 verify
```

The verifier checks:
- Acquisition autopilot is active.
- AI reads data + performs automated refinements.
- Outbound is producing qualified calls.
- Avg qualified calls/day is at least 2.
- Sales OS is operating and improving.
- Close-rate uplift reaches 2x+ versus the first 10 days.
- F2A loop is spotting bottlenecks and applying fixes.

## Data model
- `leads`: lead lifecycle + qualification score.
- `outreach_events`: reply/booking/qualification outcomes.
- `sales_calls`: sales outcomes by playbook.
- `daily_metrics`: KPI rollups.
- `templates` and `playbooks`: continuously tuned policies.
- `f2a_actions`: every automated optimization decision.

## Important scope note
This is a fully functioning **local autonomous system** with persistent state and self-optimization logic.
It is simulation-backed by default; real email/CRM/calendar/LLM integrations can be plugged in at the same decision points.
