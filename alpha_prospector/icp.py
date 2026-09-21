"""Ideal Customer Profile: the one config that drives sourcing, filtering and scoring."""

from __future__ import annotations

from typing import Any

DEFAULT_WEIGHTS = {"fit": 35, "hiring": 30, "funding": 15, "momentum": 10, "reachability": 10}

DEFAULT_ICP: dict[str, Any] = {
    "name": "",
    "offering": "",
    "industries": [],
    "exclude_industries": ["staffing", "recruiting"],
    "employee_range": [0, 0],
    "countries": ["US"],
    "location": "",
    "hiring_keywords": [],
    "hiring_recency_days": 14,
    "target_titles": [],
    "target_departments": ["c_suite", "sales"],
    "exclude_companies": [],
    "exclude_domains": [],
    "weights": DEFAULT_WEIGHTS,
}

EMAIL_DEPARTMENTS = {
    "c_suite", "product", "engineering_technical", "design", "education", "finance",
    "human_resources", "information_technology", "legal", "marketing", "medical_health",
    "operations", "sales", "consulting",
}


class IcpError(ValueError):
    pass


def validate_icp(data: dict[str, Any]) -> dict[str, Any]:
    """Merge with defaults and check the fields the pipeline depends on."""
    if not isinstance(data, dict):
        raise IcpError("ICP must be a JSON object.")
    unknown = set(data) - set(DEFAULT_ICP)
    if unknown:
        raise IcpError(f"Unknown ICP fields: {sorted(unknown)}")
    icp = {**DEFAULT_ICP, **data}
    icp["weights"] = {**DEFAULT_WEIGHTS, **(data.get("weights") or {})}

    for key in ("industries", "exclude_industries", "countries", "hiring_keywords",
                "target_titles", "target_departments", "exclude_companies", "exclude_domains"):
        if not isinstance(icp[key], list) or not all(isinstance(v, str) for v in icp[key]):
            raise IcpError(f"'{key}' must be a list of strings.")
    if not icp["hiring_keywords"]:
        raise IcpError("'hiring_keywords' needs at least one job title or keyword to source from.")
    if not icp["target_titles"]:
        raise IcpError("'target_titles' needs at least one decision-maker title.")
    bad = set(icp["target_departments"]) - EMAIL_DEPARTMENTS
    if bad:
        raise IcpError(f"Unknown target_departments {sorted(bad)}. Allowed: {sorted(EMAIL_DEPARTMENTS)}")

    rng = icp["employee_range"]
    if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(n, int) and n >= 0 for n in rng)):
        raise IcpError("'employee_range' must be [min, max] integers; use [0, 0] for any size.")
    if rng[1] and rng[0] > rng[1]:
        raise IcpError("'employee_range' min is greater than max.")

    weights = icp["weights"]
    if set(weights) != set(DEFAULT_WEIGHTS) or any(not isinstance(v, (int, float)) or v < 0 for v in weights.values()):
        raise IcpError(f"'weights' must have non-negative numbers for exactly {sorted(DEFAULT_WEIGHTS)}.")
    if sum(weights.values()) <= 0:
        raise IcpError("'weights' must sum to more than zero.")
    if not isinstance(icp["hiring_recency_days"], int) or icp["hiring_recency_days"] < 1:
        raise IcpError("'hiring_recency_days' must be a positive integer.")
    return icp
