"""Lead export: one row per contact (or one company row when no contact is known yet)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .db import Store
from .resolve import normalize_name

COLUMNS = [
    "rank", "score", "company", "domain", "website", "industry", "size", "hq", "country",
    "open_roles", "newest_role", "role_titles", "funding", "investors",
    "contact_name", "contact_title", "title_match", "contact_linkedin", "email", "email_type", "email_verification",
    "score_fit", "score_hiring", "score_funding", "score_momentum", "score_reachability", "why",
    "linkedin_url", "crunchbase_url", "sources",
]


def build_rows(store: Store, min_score: float = 0, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    targets = (store.get_icp() or {}).get("target_titles") or []

    def is_target(title: str | None) -> bool:
        text = f" {normalize_name(title)} "
        return any(all(f" {w} " in text for w in normalize_name(t).split()) for t in targets if normalize_name(t))
    for rank, cid in enumerate(store.ranked_company_ids(min_score, limit), start=1):
        company = store.get_company(cid) or {}
        score = store.get_score(cid) or {"total": None, "parts": {}, "reasons": []}
        jobs = store.signals(cid, "hiring")
        enrich = company.get("enrichment") or {}
        li_funding = (enrich.get("linkedin") or {}).get("funding") or {}
        cb = enrich.get("crunchbase") or {}
        funding = " ".join(str(v) for v in (li_funding.get("last_round_type"), li_funding.get("last_round_date")) if v)
        if not funding and cb.get("numFundingRounds"):
            funding = f"{cb['numFundingRounds']} round(s)"
        investors = ", ".join(i if isinstance(i, str) else str(i.get("name", "")) for i in (cb.get("investors") or [])[:5])
        base = {
            "rank": rank, "score": score["total"], "company": company.get("name"), "domain": company.get("domain"),
            "website": company.get("website"), "industry": company.get("industry"), "size": company.get("size_band"),
            "hq": company.get("hq"), "country": company.get("country"), "open_roles": len(jobs),
            "newest_role": max((j["observed_at"] or "" for j in jobs), default="")[:10],
            "role_titles": "; ".join(sorted({j["title"] for j in jobs})[:5]), "funding": funding,
            "investors": investors, "why": " | ".join(score["reasons"]),
            "linkedin_url": company.get("linkedin_url"), "crunchbase_url": company.get("crunchbase_url"),
            "sources": ", ".join(sorted({company.get("source") or "", *[k for k in enrich if k != "status"]} - {""})),
            **{f"score_{k}": v for k, v in score["parts"].items()},
        }
        emails = store.emails(cid)
        by_contact = {e["contact_id"]: e for e in emails if e["contact_id"]}
        inbox = next((e for e in emails if e["kind"] == "company"), None)
        # Department filters return neighbours of the buyer too; people holding a target title go first.
        contacts = sorted(store.contacts(cid), key=lambda c: not is_target(c["title"]))
        for contact in contacts or [None]:
            mail = by_contact.get(contact["id"]) if contact else None
            mail = mail or inbox
            rows.append({**base,
                         "contact_name": contact["full_name"] if contact else "",
                         "contact_title": contact["title"] if contact else "",
                         "title_match": ("yes" if is_target(contact["title"]) else "no") if contact else "",
                         "contact_linkedin": contact["linkedin_url"] if contact else "",
                         "email": mail["address"] if mail else "",
                         "email_type": mail["kind"] if mail else "",
                         "email_verification": (mail["verification"] or "not checked") if mail else ""})
    return rows


def export_leads(store: Store, path: Path | str, fmt: str = "csv", min_score: float = 0,
                 limit: int | None = None) -> dict[str, Any]:
    rows = build_rows(store, min_score, limit)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "json":
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    elif fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ValueError("xlsx export needs openpyxl: pip install 'alphaosint-prospector[xlsx]'") from exc
        book = Workbook()
        sheet = book.active
        sheet.title = "Leads"
        sheet.append(COLUMNS)
        for row in rows:
            sheet.append([row.get(col) for col in COLUMNS])
        book.save(path)
    else:
        raise ValueError("Format must be csv, json or xlsx.")
    return {"path": str(path), "rows": len(rows), "companies": len({r["company"] for r in rows})}
