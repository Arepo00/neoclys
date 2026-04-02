#!/usr/bin/env python3
"""Production-oriented SaaS control plane for Neocly AI OS.

Adds authentication, RBAC, tenant isolation, billing stubs, rate limiting,
audit logging, idempotency keys, and admin/client APIs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from neocly_os import NeoclyOS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return salt, digest


class ControlPlane:
    def __init__(self, db_path: str = "control.db", token_secret: str = "change-me") -> None:
        self.db_path = db_path
        self.token_secret = token_secret.encode()
        self.rate_window: dict[str, list[float]] = {}

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id INTEGER NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(org_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    org_id INTEGER PRIMARY KEY,
                    plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stripe_customer_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(org_id, key, endpoint)
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    org_id INTEGER,
                    action TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_org_and_owner(self, org_name: str, email: str, password: str) -> dict[str, Any]:
        salt, ph = hash_password(password)
        now = utcnow()
        with self.db() as conn:
            cur = conn.execute("INSERT INTO organizations(name, created_at) VALUES (?, ?)", (org_name, now))
            org_id = cur.lastrowid
            user = conn.execute(
                "INSERT INTO users(org_id, email, role, salt, password_hash, created_at) VALUES (?, ?, 'admin', ?, ?, ?)",
                (org_id, email, salt, ph, now),
            )
            user_id = user.lastrowid
            conn.execute(
                "INSERT INTO subscriptions(org_id, plan, status, updated_at) VALUES (?, 'starter', 'trial', ?)",
                (org_id, now),
            )
            self.audit(conn, user_id, org_id, "signup", {"email": email})
        # initialize isolated tenant db
        NeoclyOS(db_path=str(DATA_DIR / f"org_{org_id}.db")).init_db()
        return {"org_id": org_id, "user_id": user_id}

    def login(self, email: str, password: str) -> str | None:
        with self.db() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                return None
            _, ph = hash_password(password, row["salt"])
            if not hmac.compare_digest(ph, row["password_hash"]):
                return None
            exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)
            token_raw = f"{row['id']}|{int(exp.timestamp())}|{secrets.token_hex(12)}"
            sig = hmac.new(self.token_secret, token_raw.encode(), hashlib.sha256).hexdigest()
            token = f"{token_raw}.{sig}"
            conn.execute("INSERT INTO sessions(token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)", (token, row["id"], exp.isoformat(), utcnow()))
            self.audit(conn, row["id"], row["org_id"], "login", {})
            return token

    def auth(self, token: str | None):
        if not token:
            return None
        with self.db() as conn:
            sess = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
            if not sess:
                return None
            if dt.datetime.fromisoformat(sess["expires_at"]) < dt.datetime.now(dt.timezone.utc):
                return None
            user = conn.execute("SELECT * FROM users WHERE id=?", (sess["user_id"],)).fetchone()
            return user

    def audit(self, conn: sqlite3.Connection, user_id: int | None, org_id: int | None, action: str, metadata: dict[str, Any]):
        conn.execute(
            "INSERT INTO audit_logs(user_id, org_id, action, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, org_id, action, json.dumps(metadata), utcnow()),
        )

    def check_rate(self, ip: str, limit: int = 120, window_sec: int = 60) -> bool:
        now = dt.datetime.now().timestamp()
        arr = [t for t in self.rate_window.get(ip, []) if now - t < window_sec]
        arr.append(now)
        self.rate_window[ip] = arr
        return len(arr) <= limit

    def get_tenant_engine(self, org_id: int) -> NeoclyOS:
        return NeoclyOS(db_path=str(DATA_DIR / f"org_{org_id}.db"))


class SaaSAppHandler(BaseHTTPRequestHandler):
    cp: ControlPlane

    def _json(self, data: dict, status: int = 200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        ln = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(ln).decode() or "{}") if ln else {}

    def _token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.split(" ", 1)[1]
        return None

    def _require_user(self):
        user = self.cp.auth(self._token())
        if not user:
            self._json({"error": "unauthorized"}, 401)
            return None
        return user

    def do_GET(self):
        if not self.cp.check_rate(self.client_address[0]):
            return self._json({"error": "rate_limited"}, 429)
        path = urlparse(self.path).path
        if path == "/api/admin/orgs":
            user = self._require_user()
            if not user:
                return
            if user["role"] != "admin":
                return self._json({"error": "forbidden"}, 403)
            with self.cp.db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM organizations ORDER BY id DESC").fetchall()]
                self.cp.audit(conn, user["id"], user["org_id"], "admin_list_orgs", {})
            return self._json({"organizations": rows})

        if path == "/api/org/report":
            user = self._require_user()
            if not user:
                return
            report = self.cp.get_tenant_engine(user["org_id"]).report()
            with self.cp.db() as conn:
                self.cp.audit(conn, user["id"], user["org_id"], "org_report", {})
            return self._json(report)

        if path == "/api/integrations/status":
            return self._json({
                "email_provider": "not_configured",
                "crm": "not_configured",
                "calendar": "not_configured",
                "payments": "enabled_stub",
                "webhooks": "enabled_stub",
            })

        if path == "/":
            html = (BASE_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path in ("/styles.css", "/app.js"):
            file = BASE_DIR / path.lstrip("/")
            if file.exists():
                data = file.read_bytes()
                ct = "text/css" if path.endswith(".css") else "application/javascript"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        self._json({"error": "not_found"}, 404)

    def do_POST(self):
        if not self.cp.check_rate(self.client_address[0]):
            return self._json({"error": "rate_limited"}, 429)
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/auth/signup":
            required = ["org_name", "email", "password"]
            if any(not body.get(k) for k in required):
                return self._json({"error": "missing_fields"}, 400)
            res = self.cp.create_org_and_owner(body["org_name"], body["email"], body["password"])
            return self._json(res, 201)

        if path == "/api/auth/login":
            token = self.cp.login(body.get("email", ""), body.get("password", ""))
            if not token:
                return self._json({"error": "invalid_credentials"}, 401)
            return self._json({"token": token})

        if path == "/api/billing/subscribe":
            user = self._require_user()
            if not user:
                return
            plan = body.get("plan", "starter")
            with self.cp.db() as conn:
                conn.execute(
                    "INSERT INTO subscriptions(org_id, plan, status, updated_at) VALUES (?, ?, 'active', ?) ON CONFLICT(org_id) DO UPDATE SET plan=excluded.plan, status='active', updated_at=excluded.updated_at",
                    (user["org_id"], plan, utcnow()),
                )
                self.cp.audit(conn, user["id"], user["org_id"], "subscribe", {"plan": plan})
            return self._json({"ok": True, "plan": plan})

        if path in ("/api/org/seed", "/api/org/run"):
            user = self._require_user()
            if not user:
                return
            idem_key = self.headers.get("Idempotency-Key")
            endpoint = path
            with self.cp.db() as conn:
                if idem_key:
                    old = conn.execute("SELECT response_json FROM idempotency_keys WHERE org_id=? AND key=? AND endpoint=?", (user["org_id"], idem_key, endpoint)).fetchone()
                    if old:
                        return self._json(json.loads(old["response_json"]))

                engine = self.cp.get_tenant_engine(user["org_id"])
                engine.init_db()
                if path.endswith("seed"):
                    response = {"inserted": engine.seed_leads(int(body.get("count", 3000)))}
                    action = "org_seed"
                else:
                    response = {"results": engine.run_days(int(body.get("days", 30)))}
                    action = "org_run"

                if idem_key:
                    conn.execute(
                        "INSERT INTO idempotency_keys(org_id, key, endpoint, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user["org_id"], idem_key, endpoint, json.dumps(response), utcnow()),
                    )
                self.cp.audit(conn, user["id"], user["org_id"], action, {"endpoint": endpoint})
                return self._json(response)

        self._json({"error": "not_found"}, 404)


def serve(host: str, port: int, db_path: str, token_secret: str):
    cp = ControlPlane(db_path=db_path, token_secret=token_secret)
    cp.init()
    SaaSAppHandler.cp = cp
    server = ThreadingHTTPServer((host, port), SaaSAppHandler)
    print(f"SaaS Control Plane running on http://{host}:{port}")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("serve", nargs="?")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="control.db")
    parser.add_argument("--token-secret", default="dev-secret-change")
    args = parser.parse_args()
    serve(args.host, args.port, args.db, args.token_secret)


if __name__ == "__main__":
    main()
