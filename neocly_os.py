#!/usr/bin/env python3
"""Neocly AI OS SaaS backend + simulation engine."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

DEFAULT_DB = "neocly_os.db"
BASE_DIR = Path(__file__).resolve().parent


@dataclass
class Config:
    daily_outreach_capacity: int = 55
    reply_base_rate: float = 0.14
    booking_from_reply_base_rate: float = 0.34
    qualification_threshold: float = 0.82
    show_up_rate: float = 0.82
    close_base_rate: float = 0.20
    avg_deal_size: float = 2500.0


SEGMENT_MULTIPLIER = {
    "agency": 1.20,
    "saas": 1.05,
    "consulting": 1.10,
    "ecommerce": 0.95,
    "other": 0.90,
}


class NeoclyOS:
    def __init__(self, db_path: str = DEFAULT_DB, seed: int = 42, config: Config | None = None) -> None:
        self.db_path = db_path
        self.rng = random.Random(seed)
        self.config = config or Config()

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    segment TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    qualification_score REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    quality REAL NOT NULL,
                    send_share REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS playbooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    quality REAL NOT NULL,
                    weight REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS outreach_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    lead_id INTEGER NOT NULL,
                    template_id INTEGER NOT NULL,
                    replied INTEGER NOT NULL,
                    booked INTEGER NOT NULL,
                    qualified INTEGER NOT NULL,
                    FOREIGN KEY (lead_id) REFERENCES leads(id),
                    FOREIGN KEY (template_id) REFERENCES templates(id)
                );
                CREATE TABLE IF NOT EXISTS sales_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    lead_id INTEGER NOT NULL,
                    playbook_id INTEGER NOT NULL,
                    showed_up INTEGER NOT NULL,
                    won INTEGER NOT NULL,
                    revenue REAL NOT NULL,
                    FOREIGN KEY (lead_id) REFERENCES leads(id),
                    FOREIGN KEY (playbook_id) REFERENCES playbooks(id)
                );
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    day TEXT PRIMARY KEY,
                    outreaches INTEGER NOT NULL,
                    replies INTEGER NOT NULL,
                    bookings INTEGER NOT NULL,
                    qualified_bookings INTEGER NOT NULL,
                    calls_held INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    revenue REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS f2a_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    system TEXT NOT NULL,
                    bottleneck TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                """
            )
            if conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO templates(name, quality, send_share, active) VALUES (?, ?, ?, 1)",
                    [("Direct ROI", 1.0, 0.35), ("Case-Study Hook", 1.1, 0.40), ("Pain-Point Disrupt", 0.9, 0.25)],
                )
            if conn.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO playbooks(name, quality, weight, active) VALUES (?, ?, ?, 1)",
                    [("Diagnostic Close", 0.55, 0.5), ("Value-Gap Close", 0.55, 0.5)],
                )

    def seed_leads(self, count: int) -> int:
        segments = list(SEGMENT_MULTIPLIER)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        inserted = 0
        with self._db() as conn:
            for idx in range(count):
                n = self.rng.randint(10000, 99999)
                seg = self.rng.choice(segments)
                fit = SEGMENT_MULTIPLIER[seg] * self.rng.uniform(0.75, 1.25)
                try:
                    conn.execute(
                        "INSERT INTO leads(name, email, segment, status, qualification_score, created_at) VALUES (?, ?, ?, 'new', ?, ?)",
                        (f"Lead {n}", f"lead{n}_{idx}@example.com", seg, round(fit, 3), now),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
        return inserted

    def _pick_weighted(self, rows: Iterable[sqlite3.Row], weight_key: str) -> sqlite3.Row:
        items = list(rows)
        return self.rng.choices(items, weights=[max(float(i[weight_key]), 0.001) for i in items], k=1)[0]

    def _run_outbound(self, conn: sqlite3.Connection, day: str) -> tuple[int, int, int, int]:
        leads = conn.execute("SELECT * FROM leads WHERE status='new' ORDER BY id LIMIT ?", (self.config.daily_outreach_capacity,)).fetchall()
        templates = conn.execute("SELECT * FROM templates WHERE active=1").fetchall()

        out = rep = book = qual = 0
        for lead in leads:
            tpl = self._pick_weighted(templates, "send_share")
            mult = SEGMENT_MULTIPLIER.get(lead["segment"], 1.0)
            replied = int(self.rng.random() < min(0.95, self.config.reply_base_rate * tpl["quality"] * mult))
            booked = qualified = 0
            if replied:
                booked = int(self.rng.random() < min(0.9, self.config.booking_from_reply_base_rate * tpl["quality"] * mult))
                qualified = int(booked and lead["qualification_score"] >= self.config.qualification_threshold)

            conn.execute(
                "INSERT INTO outreach_events(day, lead_id, template_id, replied, booked, qualified) VALUES (?, ?, ?, ?, ?, ?)",
                (day, lead["id"], tpl["id"], replied, booked, qualified),
            )
            status = "booked" if qualified else ("unqualified_booked" if booked else ("replied" if replied else "contacted"))
            conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead["id"]))
            out += 1
            rep += replied
            book += booked
            qual += qualified
        return out, rep, book, qual

    def _run_sales_os(self, conn: sqlite3.Connection, day: str) -> tuple[int, int, float]:
        booked = conn.execute("SELECT * FROM leads WHERE status='booked' ORDER BY id").fetchall()
        held = wins = 0
        revenue = 0.0
        for lead in booked:
            pb = self._pick_weighted(conn.execute("SELECT * FROM playbooks WHERE active=1").fetchall(), "weight")
            showed = int(self.rng.random() < self.config.show_up_rate)
            won = 0
            deal = 0.0
            if showed:
                mult = SEGMENT_MULTIPLIER.get(lead["segment"], 1.0)
                won = int(self.rng.random() < min(0.9, self.config.close_base_rate * pb["quality"] * mult))
                if won:
                    deal = round(self.config.avg_deal_size * mult * self.rng.uniform(0.8, 1.4), 2)
                if won:
                    conn.execute("UPDATE playbooks SET quality=MIN(2.0, quality + 0.12), weight=MIN(3.0, weight + 0.07) WHERE id=?", (pb["id"],))
                else:
                    conn.execute("UPDATE playbooks SET quality=MAX(0.5, quality - 0.01), weight=MAX(0.2, weight - 0.01) WHERE id=?", (pb["id"],))

            conn.execute(
                "INSERT INTO sales_calls(day, lead_id, playbook_id, showed_up, won, revenue) VALUES (?, ?, ?, ?, ?, ?)",
                (day, lead["id"], pb["id"], showed, won, deal),
            )
            conn.execute("UPDATE leads SET status=? WHERE id=?", ("won" if won else ("lost" if showed else "no_show"), lead["id"]))
            held += showed
            wins += won
            revenue += deal
        return held, wins, round(revenue, 2)

    def _f2a_loop(self, conn: sqlite3.Connection, day: str) -> None:
        stats = conn.execute(
            "SELECT template_id, COUNT(*) sent, SUM(qualified) qual FROM outreach_events WHERE day >= date(?, '-6 day') GROUP BY template_id",
            (day,),
        ).fetchall()
        if stats:
            rate = lambda r: (r["qual"] or 0) / (r["sent"] or 1)
            best, worst = max(stats, key=rate), min(stats, key=rate)
            conn.execute("UPDATE templates SET quality=MIN(1.9, quality+0.06) WHERE id=?", (best["template_id"],))
            conn.execute("UPDATE templates SET quality=MAX(0.5, quality-0.04) WHERE id=?", (worst["template_id"],))
            tpls = conn.execute("SELECT id, quality FROM templates WHERE active=1").fetchall()
            total = sum(t["quality"] for t in tpls)
            for t in tpls:
                conn.execute("UPDATE templates SET send_share=? WHERE id=?", ((t["quality"] / total) if total else 1 / len(tpls), t["id"]))
            conn.execute(
                "INSERT INTO f2a_actions(day, system, bottleneck, action, details) VALUES (?, 'outbound', 'qualified booking variance', 'template_rebalance', ?)",
                (day, json.dumps({"best_template_id": best["template_id"], "worst_template_id": worst["template_id"]})),
            )

        calls = conn.execute(
            "SELECT playbook_id, SUM(showed_up) held, SUM(won) wins FROM sales_calls WHERE day >= date(?, '-13 day') GROUP BY playbook_id",
            (day,),
        ).fetchall()
        if calls:
            rate = lambda r: (r["wins"] or 0) / (r["held"] or 1)
            best, worst = max(calls, key=rate), min(calls, key=rate)
            conn.execute("UPDATE playbooks SET quality=MIN(2.0, quality+0.05), weight=MIN(3.0, weight+0.04) WHERE id=?", (best["playbook_id"],))
            conn.execute("UPDATE playbooks SET quality=MAX(0.5, quality-0.03), weight=MAX(0.2, weight-0.02) WHERE id=?", (worst["playbook_id"],))
            conn.execute(
                "INSERT INTO f2a_actions(day, system, bottleneck, action, details) VALUES (?, 'sales', 'close-rate leakage', 'playbook_rebalance', ?)",
                (day, json.dumps({"best_playbook_id": best["playbook_id"], "worst_playbook_id": worst["playbook_id"]})),
            )

    def run_day(self, day: str) -> dict[str, float | int | str]:
        with self._db() as conn:
            out, rep, book, qual = self._run_outbound(conn, day)
            held, wins, rev = self._run_sales_os(conn, day)
            self._f2a_loop(conn, day)
            conn.execute(
                "INSERT OR REPLACE INTO daily_metrics(day, outreaches, replies, bookings, qualified_bookings, calls_held, wins, revenue) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (day, out, rep, book, qual, held, wins, rev),
            )
        return {"day": day, "outreaches": out, "replies": rep, "bookings": book, "qualified_bookings": qual, "calls_held": held, "wins": wins, "revenue": rev}

    def run_days(self, days: int, start: dt.date | None = None) -> list[dict[str, float | int | str]]:
        start = start or dt.date.today()
        return [self.run_day((start + dt.timedelta(days=i)).isoformat()) for i in range(days)]

    def report(self) -> dict[str, float | int | str | None]:
        with self._db() as conn:
            agg = conn.execute("SELECT COALESCE(SUM(outreaches),0) outreaches, COALESCE(SUM(replies),0) replies, COALESCE(SUM(bookings),0) bookings, COALESCE(SUM(qualified_bookings),0) qualified_bookings, COALESCE(SUM(calls_held),0) calls_held, COALESCE(SUM(wins),0) wins, COALESCE(SUM(revenue),0) revenue FROM daily_metrics").fetchone()
            days = conn.execute("SELECT COUNT(*) n FROM daily_metrics").fetchone()["n"]
            f2a_actions = conn.execute("SELECT COUNT(*) n FROM f2a_actions").fetchone()["n"]
            template = conn.execute("SELECT name FROM templates ORDER BY quality DESC LIMIT 1").fetchone()
            playbook = conn.execute("SELECT name FROM playbooks ORDER BY quality DESC LIMIT 1").fetchone()
            early = conn.execute("SELECT COALESCE(SUM(wins),0) w, COALESCE(SUM(calls_held),0) c FROM (SELECT wins, calls_held FROM daily_metrics ORDER BY day ASC LIMIT 10)").fetchone()
            late = conn.execute("SELECT COALESCE(SUM(wins),0) w, COALESCE(SUM(calls_held),0) c FROM (SELECT wins, calls_held FROM daily_metrics ORDER BY day DESC LIMIT 10)").fetchone()

        early_close = (early["w"] / early["c"]) if early["c"] else 0.0
        late_close = (late["w"] / late["c"]) if late["c"] else 0.0
        uplift = (late_close / early_close) if early_close else 0.0
        outreaches = agg["outreaches"]
        qualified = agg["qualified_bookings"]
        calls = agg["calls_held"]
        return {
            "days": days,
            "outreaches": outreaches,
            "replies": agg["replies"],
            "bookings": agg["bookings"],
            "qualified_bookings": qualified,
            "calls_held": calls,
            "wins": agg["wins"],
            "revenue": round(agg["revenue"], 2),
            "avg_qualified_calls_per_day": round((qualified / days), 3) if days else 0.0,
            "reply_rate": round((agg["replies"] / outreaches), 4) if outreaches else 0.0,
            "booking_rate": round((qualified / outreaches), 4) if outreaches else 0.0,
            "close_rate": round((agg["wins"] / calls), 4) if calls else 0.0,
            "close_rate_uplift_vs_first_10_days": round(uplift, 3),
            "f2a_actions": f2a_actions,
            "top_template": template["name"] if template else None,
            "top_playbook": playbook["name"] if playbook else None,
        }


def run_verification(db_path: str, seed: int) -> dict[str, object]:
    osys = NeoclyOS(db_path=db_path, seed=seed)
    osys.init_db()
    osys.seed_leads(3000)
    osys.run_days(60)
    rep = osys.report()
    checks = {
        "acquisition_system_autopilot": rep["qualified_bookings"] > 0 and rep["outreaches"] > 0,
        "reads_data_and_refines": rep["f2a_actions"] >= 60,
        "ai_outbound_exists": rep["booking_rate"] > 0,
        "qualified_calls_2_to_3_plus_daily": rep["avg_qualified_calls_per_day"] >= 2.0,
        "ai_sales_os_exists": rep["calls_held"] > 0,
        "sales_uplift_2x_plus": rep["close_rate_uplift_vs_first_10_days"] >= 2.0,
        "f2a_spots_and_fixes": rep["f2a_actions"] > 0,
    }
    return {"report": rep, "checks": checks, "all_pass": all(checks.values())}


class SaaSHandler(BaseHTTPRequestHandler):
    osys: NeoclyOS

    def _json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        ln = int(self.headers.get("Content-Length", 0))
        if not ln:
            return {}
        return json.loads(self.rfile.read(ln).decode() or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/report":
            return self._json(self.osys.report())
        if path == "/api/verify":
            return self._json(run_verification(self.osys.db_path, seed=19))
        if path == "/":
            return self._serve_file(BASE_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/styles.css":
            return self._serve_file(BASE_DIR / "styles.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self._serve_file(BASE_DIR / "app.js", "application/javascript; charset=utf-8")
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/init":
            self.osys.init_db()
            return self._json({"ok": True})
        if path == "/api/seed":
            c = int(body.get("count", 3000))
            self.osys.init_db()
            return self._json({"inserted": self.osys.seed_leads(c)})
        if path == "/api/run":
            d = int(body.get("days", 60))
            self.osys.init_db()
            return self._json({"results": self.osys.run_days(d)})
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(osys: NeoclyOS, host: str, port: int) -> None:
    SaaSHandler.osys = osys
    server = ThreadingHTTPServer((host, port), SaaSHandler)
    print(f"Neocly SaaS running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Neocly AI OS")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--seed", type=int, default=42)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_seed = sub.add_parser("seed-leads")
    p_seed.add_argument("count", type=int)
    p_run = sub.add_parser("run")
    p_run.add_argument("days", type=int)
    sub.add_parser("report")
    sub.add_parser("verify")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()
    osys = NeoclyOS(db_path=args.db, seed=args.seed)

    if args.cmd == "init":
        osys.init_db(); print("initialized"); return
    osys.init_db()
    if args.cmd == "seed-leads":
        print(json.dumps({"inserted": osys.seed_leads(args.count)}))
    elif args.cmd == "run":
        print(json.dumps(osys.run_days(args.days), indent=2))
    elif args.cmd == "report":
        print(json.dumps(osys.report(), indent=2))
    elif args.cmd == "verify":
        print(json.dumps(run_verification(args.db, args.seed), indent=2))
    elif args.cmd == "serve":
        serve(osys, args.host, args.port)


if __name__ == "__main__":
    main()
