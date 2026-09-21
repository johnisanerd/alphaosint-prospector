"""SQLite lead store. One file, no server. Companies are first-class; everything hangs off them."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resolve import normalize_name, person_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS icp (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    domain TEXT,
    website TEXT,
    industry TEXT,
    size_band TEXT,
    employees_min INTEGER,
    employees_max INTEGER,
    hq TEXT,
    country TEXT,
    description TEXT,
    linkedin_url TEXT,
    crunchbase_url TEXT,
    indeed_url TEXT,
    source TEXT,
    first_seen TEXT NOT NULL,
    enriched_at TEXT,
    enrichment TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(norm_name);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT,
    source_actor TEXT,
    run_id TEXT,
    dedupe_key TEXT NOT NULL,
    UNIQUE(company_id, type, dedupe_key)
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    full_name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    title TEXT,
    department TEXT,
    seniority TEXT,
    linkedin_url TEXT,
    location TEXT,
    source TEXT,
    UNIQUE(company_id, name_key)
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    address TEXT NOT NULL,
    kind TEXT NOT NULL,
    verification TEXT,
    source TEXT,
    found_at TEXT NOT NULL,
    UNIQUE(company_id, address)
);
CREATE TABLE IF NOT EXISTS scores (
    company_id INTEGER PRIMARY KEY REFERENCES companies(id),
    total REAL NOT NULL,
    parts TEXT NOT NULL,
    reasons TEXT NOT NULL,
    scored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,
    items INTEGER NOT NULL DEFAULT 0,
    est_cost REAL NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    input TEXT NOT NULL DEFAULT '{}'
);
"""

COMPANY_FIELDS = (
    "website", "industry", "size_band", "employees_min", "employees_max", "hq", "country",
    "description", "linkedin_url", "crunchbase_url", "indeed_url",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- ICP -------------------------------------------------------------
    def set_icp(self, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO icp (id, data, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (json.dumps(data), now()),
        )
        self.conn.commit()

    def get_icp(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM icp WHERE id = 1").fetchone()
        return json.loads(row["data"]) if row else None

    # -- companies -------------------------------------------------------
    def find_company(self, name: str | None, domain: str | None) -> sqlite3.Row | None:
        if domain:
            row = self.conn.execute("SELECT * FROM companies WHERE domain = ?", (domain,)).fetchone()
            if row:
                return row
        norm = normalize_name(name)
        if not norm:
            return None
        rows = self.conn.execute("SELECT * FROM companies WHERE norm_name = ?", (norm,)).fetchall()
        for row in rows:
            # Same name with two different known domains = two different companies.
            if not (domain and row["domain"] and row["domain"] != domain):
                return row
        return None

    def upsert_company(self, name: str, domain: str | None = None, source: str = "", **fields: Any) -> int:
        """Insert or fill blanks. Existing non-empty values are never overwritten."""
        existing = self.find_company(name, domain)
        clean = {k: v for k, v in fields.items() if k in COMPANY_FIELDS and v not in (None, "", [])}
        if existing is None:
            cols = ["name", "norm_name", "domain", "source", "first_seen", *clean]
            vals = [name, normalize_name(name), domain, source, now(), *clean.values()]
            cur = self.conn.execute(
                f"INSERT INTO companies ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals
            )
            self.conn.commit()
            return int(cur.lastrowid)
        updates = {k: v for k, v in clean.items() if existing[k] in (None, "")}
        if domain and not existing["domain"]:
            updates["domain"] = domain
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            self.conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", [*updates.values(), existing["id"]])
            self.conn.commit()
        return int(existing["id"])

    def merge_enrichment(self, company_id: int, source: str, payload: dict[str, Any]) -> None:
        row = self.conn.execute("SELECT enrichment FROM companies WHERE id = ?", (company_id,)).fetchone()
        data = json.loads(row["enrichment"] or "{}")
        data[source] = payload
        self.conn.execute(
            "UPDATE companies SET enrichment = ?, enriched_at = ? WHERE id = ?",
            (json.dumps(data), now(), company_id),
        )
        self.conn.commit()

    def get_company(self, company_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["enrichment"] = json.loads(data["enrichment"] or "{}")
        return data

    def list_companies(self, only_unenriched: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM companies"
        if only_unenriched:
            sql += " WHERE enriched_at IS NULL"
        out = []
        for row in self.conn.execute(sql + " ORDER BY id"):
            data = dict(row)
            data["enrichment"] = json.loads(data["enrichment"] or "{}")
            out.append(data)
        return out

    # -- signals / contacts / emails --------------------------------------
    def add_signal(self, company_id: int, type_: str, title: str, dedupe_key: str, *,
                   detail: dict[str, Any] | None = None, observed_at: str | None = None,
                   source_actor: str = "", run_id: str | None = None) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO signals (company_id, type, title, detail, observed_at, source_actor, run_id, dedupe_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, type_, title, json.dumps(detail or {}), observed_at, source_actor, run_id, dedupe_key),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def signals(self, company_id: int, type_: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM signals WHERE company_id = ?", [company_id]
        if type_:
            sql += " AND type = ?"
            args.append(type_)
        out = []
        for row in self.conn.execute(sql + " ORDER BY observed_at DESC", args):
            data = dict(row)
            data["detail"] = json.loads(data["detail"] or "{}")
            out.append(data)
        return out

    def add_contact(self, company_id: int, full_name: str, *, title: str | None = None,
                    department: str | None = None, seniority: str | None = None,
                    linkedin_url: str | None = None, location: str | None = None, source: str = "") -> int | None:
        key = person_key(full_name)
        if not key:
            return None
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? AND name_key = ?", (company_id, key)
        ).fetchone()
        if row is None:
            cur = self.conn.execute(
                "INSERT INTO contacts (company_id, full_name, name_key, title, department, seniority, linkedin_url, location, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (company_id, full_name.strip(), key, title, department, seniority, linkedin_url, location, source),
            )
            self.conn.commit()
            return int(cur.lastrowid)
        fills = {k: v for k, v in {"title": title, "department": department, "seniority": seniority,
                                   "linkedin_url": linkedin_url, "location": location}.items()
                 if v and not row[k]}
        if fills:
            sets = ", ".join(f"{k} = ?" for k in fills)
            self.conn.execute(f"UPDATE contacts SET {sets} WHERE id = ?", [*fills.values(), row["id"]])
            self.conn.commit()
        return int(row["id"])

    def contacts(self, company_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? ORDER BY id", (company_id,))]

    def add_email(self, company_id: int, address: str, *, kind: str, contact_id: int | None = None,
                  verification: str | None = None, source: str = "") -> bool:
        address = address.strip().lower()
        if "@" not in address:
            return False
        cur = self.conn.execute(
            "INSERT INTO emails (company_id, contact_id, address, kind, verification, source, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(company_id, address) DO UPDATE SET "
            "verification = COALESCE(excluded.verification, emails.verification), "
            "contact_id = COALESCE(emails.contact_id, excluded.contact_id)",
            (company_id, contact_id, address, kind, verification, source, now()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def emails(self, company_id: int, usable_only: bool = True) -> list[dict[str, Any]]:
        """Addresses for an account. Verified-bad ones stay stored (so they are not re-bought) but hidden."""
        sql = "SELECT * FROM emails WHERE company_id = ?"
        if usable_only:
            sql += " AND COALESCE(verification, '') NOT IN ('invalid', 'disposable')"
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY id", (company_id,))]

    # -- scores ------------------------------------------------------------
    def save_score(self, company_id: int, total: float, parts: dict[str, float], reasons: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO scores (company_id, total, parts, reasons, scored_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(company_id) DO UPDATE SET total = excluded.total, parts = excluded.parts, "
            "reasons = excluded.reasons, scored_at = excluded.scored_at",
            (company_id, total, json.dumps(parts), json.dumps(reasons), now()),
        )
        self.conn.commit()

    def get_score(self, company_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM scores WHERE company_id = ?", (company_id,)).fetchone()
        if row is None:
            return None
        return {"total": row["total"], "parts": json.loads(row["parts"]),
                "reasons": json.loads(row["reasons"]), "scored_at": row["scored_at"]}

    def ranked_company_ids(self, min_score: float = 0, limit: int | None = None) -> list[int]:
        sql = ("SELECT c.id FROM companies c LEFT JOIN scores s ON s.company_id = c.id "
               "WHERE COALESCE(s.total, 0) >= ? ORDER BY COALESCE(s.total, 0) DESC, c.id")
        args: list[Any] = [min_score]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [int(r["id"]) for r in self.conn.execute(sql, args)]

    # -- runs ----------------------------------------------------------------
    def log_run(self, actor: str, run_id: str | None, status: str, items: int, est_cost: float,
                cost: float, run_input: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO runs (actor, run_id, status, items, est_cost, cost, started_at, input) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (actor, run_id, status, items, est_cost, cost, now(), json.dumps(run_input)),
        )
        self.conn.commit()

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT actor, run_id, status, items, est_cost, cost, started_at FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    def spend(self, since: str | None = None) -> float:
        sql, args = "SELECT COALESCE(SUM(cost), 0) AS total FROM runs", []
        if since:
            sql += " WHERE started_at >= ?"
            args.append(since)
        return float(self.conn.execute(sql, args).fetchone()["total"])
