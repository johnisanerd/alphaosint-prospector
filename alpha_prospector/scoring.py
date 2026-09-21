"""Deterministic 0-100 lead score. Same data in, same score out, with a reason for every point.

Unknown data scores zero for its part (fail closed) and says so in the reasons, so an
unenriched account never outranks an enriched one by accident.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

PARTS = ("fit", "hiring", "funding", "momentum", "reachability")


def parse_size_band(text: str | None) -> tuple[int | None, int | None]:
    """'51-200 employees' -> (51, 200); '10,001+ employees' -> (10001, None)."""
    if not text:
        return None, None
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)]
    if not nums:
        return None, None
    if len(nums) == 1:
        return (nums[0], None) if "+" in text else (nums[0], nums[0])
    return nums[0], nums[1]


def _parse_day(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    for candidate in (value, value[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    match = re.search(r"(19|20)\d{2}", value)
    return date(int(match.group(0)), 1, 1) if match else None


def _fit(company: dict[str, Any], icp: dict[str, Any]) -> tuple[float, list[str]]:
    reasons, score = [], 0.0
    industry = " ".join(str(company.get(k) or "") for k in ("industry", "description")).lower()
    wanted = [w.lower() for w in icp["industries"]]
    if not wanted:
        score += 0.4
    elif not (company.get("industry") or company.get("description")):
        reasons.append("fit: industry unknown")
    elif any(w in industry for w in wanted):
        score += 0.4
        reasons.append(f"fit: industry matches ({company.get('industry') or 'description'})")
    else:
        reasons.append(f"fit: industry '{company.get('industry')}' not in ICP")

    lo, hi = icp["employee_range"]
    cmin, cmax = company.get("employees_min"), company.get("employees_max")
    if not lo and not hi:
        score += 0.4
    elif cmin is None:
        reasons.append("fit: headcount unknown")
    else:
        top = cmax if cmax is not None else cmin
        if top >= lo and (not hi or cmin <= hi):
            score += 0.4
            reasons.append(f"fit: headcount {company.get('size_band') or cmin} in range")
        else:
            reasons.append(f"fit: headcount {company.get('size_band') or cmin} outside {lo}-{hi or 'any'}")

    countries = [c.upper() for c in icp["countries"]]
    country = (company.get("country") or "").upper()
    if not countries:
        score += 0.2
    elif country and country in countries:
        score += 0.2
        reasons.append(f"fit: country {country}")
    elif not country:
        reasons.append("fit: country unknown")
    else:
        reasons.append(f"fit: country {country} not in ICP")
    return score, reasons


def _hiring(signals: list[dict[str, Any]], icp: dict[str, Any], today: date) -> tuple[float, list[str]]:
    jobs = [s for s in signals if s["type"] == "hiring"]
    if not jobs:
        return 0.0, ["hiring: no matching open roles found"]
    volume = min(1.0, len(jobs) / 5)
    days = [(today - d).days for d in (_parse_day(s.get("observed_at")) for s in jobs) if d]
    window = icp["hiring_recency_days"]
    if days:
        newest = max(0, min(days))
        recency = 1.0 if newest <= window else max(0.0, 1 - (newest - window) / (2 * window))
        age = f"newest {newest}d ago"
    else:
        recency, age = 0.0, "posting dates unknown"
    urgent = any(s["detail"].get("urgent") or s["detail"].get("multiple") for s in jobs)
    titles = ", ".join(sorted({s["title"] for s in jobs})[:3])
    return 0.6 * volume + 0.4 * recency, [
        f"hiring: {len(jobs)} matching role(s), {age}" + (", urgent/multiple hires" if urgent else "") + f" ({titles})"
    ]


def _funding(company: dict[str, Any], today: date) -> tuple[float, list[str]]:
    enrich = company.get("enrichment") or {}
    li = (enrich.get("linkedin") or {}).get("funding") or {}
    cb = enrich.get("crunchbase") or {}
    last = _parse_day(li.get("last_round_date"))
    label = li.get("last_round_type") or "round"
    if last:
        months = (today - last).days / 30.4
        score = 1.0 if months <= 6 else 0.7 if months <= 12 else 0.4 if months <= 24 else 0.2
        return score, [f"funding: {label} about {int(months)} months ago"]
    rounds = cb.get("numFundingRounds") or li.get("rounds")
    if rounds:
        return 0.2, [f"funding: {rounds} round(s) on record, date not public"]
    if not enrich:
        return 0.0, ["funding: not enriched"]
    return 0.0, ["funding: no rounds found"]


def _momentum(company: dict[str, Any], signals: list[dict[str, Any]]) -> tuple[float, list[str]]:
    cb = (company.get("enrichment") or {}).get("crunchbase") or {}
    score, reasons = 0.0, []
    growth = cb.get("monthlyVisitsGrowth")
    if isinstance(growth, (int, float)) and growth > 0:
        score += 0.5
        reasons.append(f"momentum: web traffic up {growth:g}%")
    if any(s["type"] == "hiring" and (s["detail"].get("urgent") or s["detail"].get("multiple")) for s in signals):
        score += 0.5
        reasons.append("momentum: urgent or multi-seat hiring")
    return score, reasons or ["momentum: no growth data"]


def _reachability(contacts: list[dict[str, Any]], emails: list[dict[str, Any]]) -> tuple[float, list[str]]:
    personal = [e for e in emails if e["kind"] == "person"]
    if any(e["verification"] == "ok" for e in personal):
        return 1.0, ["reachability: verified decision-maker email"]
    if personal:
        return 0.7, ["reachability: decision-maker email, not verified"]
    if emails:
        return 0.5, ["reachability: company inbox only"]
    if contacts:
        return 0.3, ["reachability: named decision-maker, no email yet"]
    return 0.0, ["reachability: no contact found"]


def score_company(company: dict[str, Any], signals: list[dict[str, Any]], contacts: list[dict[str, Any]],
                  emails: list[dict[str, Any]], icp: dict[str, Any],
                  today: date | None = None) -> tuple[float, dict[str, float], list[str]]:
    today = today or datetime.now(timezone.utc).date()
    raw = {
        "fit": _fit(company, icp),
        "hiring": _hiring(signals, icp, today),
        "funding": _funding(company, today),
        "momentum": _momentum(company, signals),
        "reachability": _reachability(contacts, emails),
    }
    weights = icp["weights"]
    scale = 100 / sum(weights.values())
    parts = {name: round(raw[name][0] * weights[name] * scale, 1) for name in PARTS}
    reasons = [r for name in PARTS for r in raw[name][1]]
    return round(sum(parts.values()), 1), parts, reasons
