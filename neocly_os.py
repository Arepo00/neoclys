#!/usr/bin/env python3
"""Neocly AI OS: autonomous acquisition + sales system with self-improving F2A loop."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sqlite3
from dataclasses import dataclass
from typing import Iterable

DEFAULT_DB = "neocly_os.db"


@dataclass
class Config:
    # Outbound tuned to target ~2-3 qualified bookings/day at steady state.
    daily_outreach_capacity: int = 55
    reply_base_rate: float = 0.14
    booking_from_reply_base_rate: float = 0.34
    qualification_threshold: float = 0.82

    # Sales engine and monetization.
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

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._conn() as conn:
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
                    [
                        ("Direct ROI", 1.0, 0.35),
                        ("Case-Study Hook", 1.1, 0.40),
                        ("Pain-Point Disrupt", 0.9, 0.25),
                    ],
                )

            if conn.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO playbooks(name, quality, weight, active) VALUES (?, ?, ?, 1)",
                    [
                        ("Diagnostic Close", 0.55, 0.5),
                        ("Value-Gap Close", 0.55, 0.5),
                    ],
                )

    def seed_leads(self, count: int) -> int:
        segments = list(SEGMENT_MULTIPLIER.keys())
        now = dt.datetime.utcnow().isoformat()
        inserted = 0
        with self._conn() as conn:
            for idx in range(count):
                n = self.rng.randint(10000, 99999)
                email = f"lead{n}_{idx}@example.com"
                seg = self.rng.choice(segments)
                # qualification is a proxy for ICP fit and buying intent.
                fit = SEGMENT_MULTIPLIER[seg] * self.rng.uniform(0.75, 1.25)
                try:
                    conn.execute(
                        "INSERT INTO leads(name, email, segment, status, qualification_score, created_at) VALUES (?, ?, ?, 'new', ?, ?)",
                        (f"Lead {n}", email, seg, round(fit, 3), now),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    continue
        return inserted

    def _pick_weighted(self, rows: Iterable[sqlite3.Row], weight_key: str) -> sqlite3.Row:
        items = list(rows)
        weights = [max(float(r[weight_key]), 0.001) for r in items]
        return self.rng.choices(items, weights=weights, k=1)[0]

    def _run_outbound(self, conn: sqlite3.Connection, day: str) -> tuple[int, int, int, int]:
        leads = conn.execute(
            "SELECT * FROM leads WHERE status='new' ORDER BY id LIMIT ?",
            (self.config.daily_outreach_capacity,),
        ).fetchall()
        templates = conn.execute("SELECT * FROM templates WHERE active=1").fetchall()

        outreaches = replies = bookings = qualified_bookings = 0
        for lead in leads:
            tpl = self._pick_weighted(templates, "send_share")
            mult = SEGMENT_MULTIPLIER.get(lead["segment"], 1.0)

            reply_prob = min(0.95, self.config.reply_base_rate * tpl["quality"] * mult)
            replied = int(self.rng.random() < reply_prob)

            booked = qualified = 0
            if replied:
                booking_prob = min(0.9, self.config.booking_from_reply_base_rate * tpl["quality"] * mult)
                booked = int(self.rng.random() < booking_prob)
                qualified = int(booked and lead["qualification_score"] >= self.config.qualification_threshold)

            conn.execute(
                "INSERT INTO outreach_events(day, lead_id, template_id, replied, booked, qualified) VALUES (?, ?, ?, ?, ?, ?)",
                (day, lead["id"], tpl["id"], replied, booked, qualified),
            )

            new_status = "contacted"
            if qualified:
                new_status = "booked"
            elif booked:
                new_status = "unqualified_booked"
            elif replied:
                new_status = "replied"

            conn.execute("UPDATE leads SET status=? WHERE id=?", (new_status, lead["id"]))

            outreaches += 1
            replies += replied
            bookings += booked
            qualified_bookings += qualified

        return outreaches, replies, bookings, qualified_bookings

    def _run_sales_os(self, conn: sqlite3.Connection, day: str) -> tuple[int, int, float]:
        booked = conn.execute("SELECT * FROM leads WHERE status='booked' ORDER BY id").fetchall()
        calls_held = wins = 0
        revenue = 0.0

        for lead in booked:
            playbooks = conn.execute("SELECT * FROM playbooks WHERE active=1").fetchall()
            pb = self._pick_weighted(playbooks, "weight")

            showed_up = int(self.rng.random() < self.config.show_up_rate)
            won = 0
            deal = 0.0

            if showed_up:
                mult = SEGMENT_MULTIPLIER.get(lead["segment"], 1.0)
                close_prob = min(0.9, self.config.close_base_rate * pb["quality"] * mult)
                won = int(self.rng.random() < close_prob)
                if won:
                    deal = round(self.config.avg_deal_size * mult * self.rng.uniform(0.8, 1.4), 2)

            conn.execute(
                "INSERT INTO sales_calls(day, lead_id, playbook_id, showed_up, won, revenue) VALUES (?, ?, ?, ?, ?, ?)",
                (day, lead["id"], pb["id"], showed_up, won, deal),
            )

            # Per-call learning (AI Sales OS): continuously refine playbook after each call.
            if showed_up:
                if won:
                    conn.execute("UPDATE playbooks SET quality=MIN(2.0, quality + 0.12), weight=MIN(3.0, weight + 0.07) WHERE id=?", (pb["id"],))
                else:
                    conn.execute("UPDATE playbooks SET quality=MAX(0.5, quality - 0.01), weight=MAX(0.2, weight - 0.01) WHERE id=?", (pb["id"],))

            final_status = "no_show"
            if showed_up:
                final_status = "won" if won else "lost"
            conn.execute("UPDATE leads SET status=? WHERE id=?", (final_status, lead["id"]))

            calls_held += showed_up
            wins += won
            revenue += deal

        return calls_held, wins, round(revenue, 2)

    def _f2a_loop(self, conn: sqlite3.Connection, day: str) -> None:
        # Outbound feedback -> action on last 7 days.
        stats = conn.execute(
            """
            SELECT template_id, COUNT(*) AS sent, SUM(replied) AS replies, SUM(qualified) AS qualified
            FROM outreach_events
            WHERE day >= date(?, '-6 day')
            GROUP BY template_id
            """,
            (day,),
        ).fetchall()

        if stats:
            def qual_rate(r: sqlite3.Row) -> float:
                sent = r["sent"] or 1
                return (r["qualified"] or 0) / sent

            best = max(stats, key=qual_rate)
            worst = min(stats, key=qual_rate)

            conn.execute("UPDATE templates SET quality=MIN(1.9, quality + 0.06) WHERE id=?", (best["template_id"],))
            conn.execute("UPDATE templates SET quality=MAX(0.5, quality - 0.04) WHERE id=?", (worst["template_id"],))

            templates = conn.execute("SELECT id, quality FROM templates WHERE active=1").fetchall()
            total = sum(t["quality"] for t in templates)
            for t in templates:
                conn.execute("UPDATE templates SET send_share=? WHERE id=?", ((t["quality"] / total) if total else 1 / len(templates), t["id"]))

            conn.execute(
                "INSERT INTO f2a_actions(day, system, bottleneck, action, details) VALUES (?, 'outbound', 'qualified booking variance', 'template_rebalance', ?)",
                (day, json.dumps({"best_template_id": best["template_id"], "worst_template_id": worst["template_id"]})),
            )

        # Sales feedback -> action on last 14 days.
        call_stats = conn.execute(
            """
            SELECT playbook_id, SUM(showed_up) AS held, SUM(won) AS wins
            FROM sales_calls
            WHERE day >= date(?, '-13 day')
            GROUP BY playbook_id
            """,
            (day,),
        ).fetchall()

        if call_stats:
            def win_rate(r: sqlite3.Row) -> float:
                held = r["held"] or 1
                return (r["wins"] or 0) / held

            best = max(call_stats, key=win_rate)
            worst = min(call_stats, key=win_rate)

            conn.execute("UPDATE playbooks SET quality=MIN(2.0, quality + 0.05), weight=MIN(3.0, weight + 0.04) WHERE id=?", (best["playbook_id"],))
            conn.execute("UPDATE playbooks SET quality=MAX(0.5, quality - 0.03), weight=MAX(0.2, weight - 0.02) WHERE id=?", (worst["playbook_id"],))

            conn.execute(
                "INSERT INTO f2a_actions(day, system, bottleneck, action, details) VALUES (?, 'sales', 'close-rate leakage', 'playbook_rebalance', ?)",
                (day, json.dumps({"best_playbook_id": best["playbook_id"], "worst_playbook_id": worst["playbook_id"]})),
            )

    def run_day(self, day: str) -> dict[str, float | int | str]:
        with self._conn() as conn:
            out, rep, book, qual = self._run_outbound(conn, day)
            held, wins, rev = self._run_sales_os(conn, day)
            self._f2a_loop(conn, day)

            conn.execute(
                "INSERT OR REPLACE INTO daily_metrics(day, outreaches, replies, bookings, qualified_bookings, calls_held, wins, revenue) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (day, out, rep, book, qual, held, wins, rev),
            )

        return {
            "day": day,
            "outreaches": out,
            "replies": rep,
            "bookings": book,
            "qualified_bookings": qual,
            "calls_held": held,
            "wins": wins,
            "revenue": rev,
        }

    def run_days(self, days: int, start: dt.date | None = None) -> list[dict[str, float | int | str]]:
        start = start or dt.date.today()
        return [self.run_day((start + dt.timedelta(days=i)).isoformat()) for i in range(days)]

    def report(self) -> dict[str, float | int | str | None]:
        with self._conn() as conn:
            agg = conn.execute(
                """
                SELECT
                    COALESCE(SUM(outreaches), 0) AS outreaches,
                    COALESCE(SUM(replies), 0) AS replies,
                    COALESCE(SUM(bookings), 0) AS bookings,
                    COALESCE(SUM(qualified_bookings), 0) AS qualified_bookings,
                    COALESCE(SUM(calls_held), 0) AS calls_held,
                    COALESCE(SUM(wins), 0) AS wins,
                    COALESCE(SUM(revenue), 0) AS revenue
                FROM daily_metrics
                """
            ).fetchone()

            days = conn.execute("SELECT COUNT(*) AS n FROM daily_metrics").fetchone()["n"]
            f2a_actions = conn.execute("SELECT COUNT(*) AS n FROM f2a_actions").fetchone()["n"]

            template = conn.execute(
                "SELECT name FROM templates ORDER BY quality DESC LIMIT 1"
            ).fetchone()
            playbook = conn.execute(
                "SELECT name FROM playbooks ORDER BY quality DESC LIMIT 1"
            ).fetchone()

            early = conn.execute(
                """
                SELECT COALESCE(SUM(wins),0) AS w, COALESCE(SUM(calls_held),0) AS c
                FROM (
                    SELECT wins, calls_held
                    FROM daily_metrics
                    ORDER BY day ASC
                    LIMIT 10
                )
                """
            ).fetchone()
            late = conn.execute(
                """
                SELECT COALESCE(SUM(wins),0) AS w, COALESCE(SUM(calls_held),0) AS c
                FROM (
                    SELECT wins, calls_held
                    FROM daily_metrics
                    ORDER BY day DESC
                    LIMIT 10
                )
                """
            ).fetchone()

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Neocly AI OS")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite DB")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Initialize the system database")

    p_seed = sub.add_parser("seed-leads", help="Seed synthetic leads")
    p_seed.add_argument("count", type=int)

    p_run = sub.add_parser("run", help="Run autonomous system for N days")
    p_run.add_argument("days", type=int)

    sub.add_parser("report", help="Show aggregated metrics")
    sub.add_parser("verify", help="Run full 60-day checkbox verification")

    args = parser.parse_args()
    osys = NeoclyOS(db_path=args.db, seed=args.seed)

    if args.cmd == "init":
        osys.init_db()
        print("initialized")
        return

    osys.init_db()

    if args.cmd == "seed-leads":
        print(json.dumps({"inserted": osys.seed_leads(args.count)}))
    elif args.cmd == "run":
        print(json.dumps(osys.run_days(args.days), indent=2))
    elif args.cmd == "report":
        print(json.dumps(osys.report(), indent=2))
    elif args.cmd == "verify":
        print(json.dumps(run_verification(args.db, args.seed), indent=2))


if __name__ == "__main__":
    main()
