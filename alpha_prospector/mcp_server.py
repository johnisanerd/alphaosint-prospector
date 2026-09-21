"""MCP server. Thin wrappers over pipeline.py; all spend goes through runner.Runner."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import actors, pipeline
from .config import db_path, home, load_settings
from .db import Store
from .export import export_leads as _export
from .icp import DEFAULT_ICP, IcpError, validate_icp
from .runner import ActorRunError, BudgetExceeded, Runner

mcp = MCPServer("alphaosint-prospector")


@lru_cache(maxsize=1)
def _ctx() -> tuple[Store, Runner]:
    store = Store(db_path())
    return store, Runner(store, load_settings())


def _guard(fn):
    """Turn expected failures into a structured answer the model can act on."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BudgetExceeded as exc:
            return {"error": "budget_exceeded", "message": str(exc)}
        except (ActorRunError, IcpError, ValueError) as exc:
            return {"error": type(exc).__name__, "message": str(exc)}
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    wrapper.__annotations__ = fn.__annotations__
    wrapper.__wrapped__ = fn
    return wrapper


def _icp(store: Store) -> dict[str, Any]:
    icp = store.get_icp()
    if not icp:
        raise IcpError("No ICP saved yet. Call set_icp first (see get_icp for the template).")
    return icp


def _pick(store: Store, company_ids: list[int] | None, top: int, only_unenriched: bool = False) -> list[int]:
    if company_ids:
        return company_ids
    ids = store.ranked_company_ids(limit=None)
    if only_unenriched:
        fresh = {c["id"] for c in store.list_companies(only_unenriched=True)}
        ids = [i for i in ids if i in fresh]
    return ids[:top]


@mcp.tool()
@_guard
def get_config() -> dict[str, Any]:
    """Setup status, budgets, spend so far, and lead counts. Call once per session."""
    store, runner = _ctx()
    return {
        "home": str(home()), "apify_token_set": runner.settings.has_token, "icp_saved": store.get_icp() is not None,
        "session_budget_usd": runner.settings.session_budget_usd, "call_budget_usd": runner.settings.call_budget_usd,
        "session_spend_usd": round(runner.session_spend(), 4), "companies": len(store.list_companies()),
    }


@mcp.tool()
@_guard
def get_icp() -> dict[str, Any]:
    """The saved Ideal Customer Profile, or the blank template when none is saved."""
    store, _ = _ctx()
    return {"saved": store.get_icp(), "template": DEFAULT_ICP}


@mcp.tool()
@_guard
def set_icp(icp: dict[str, Any]) -> dict[str, Any]:
    """Validate and save the ICP. Required: hiring_keywords and target_titles."""
    store, _ = _ctx()
    clean = validate_icp(icp)
    store.set_icp(clean)
    return {"saved": clean}


@mcp.tool()
@_guard
def estimate_cost(max_companies: int = 25, max_jobs_per_keyword: int = 25, enrich_top: int = 10,
                  contacts_top: int = 5, emails_top: int = 5, leads_per_domain: int = 3) -> dict[str, Any]:
    """Worst-case USD for a full pass with these limits. Spends nothing."""
    store, runner = _ctx()
    icp = _icp(store)
    names = ["x"] * enrich_top
    parts = {
        "source_indeed_jobs": runner.estimate("indeed_jobs", actors.indeed_jobs_input(icp, max_jobs_per_keyword)),
        "enrich_indeed_company": runner.estimate("indeed_company", {"mode": "keyword", "keywords": names, "resolveExact": True}),
        "enrich_linkedin": runner.estimate("linkedin_company", {"companyNames": names}),
        "enrich_crunchbase": runner.estimate("crunchbase_company", {"companyNames": names}),
        "contacts_linkedin_people": round(contacts_top * min(2, len(icp["target_titles"])) *
                                          runner.estimate("linkedin_people", {"maxResults": 3}), 4),
        "emails_contact_info": runner.estimate("contact_info", actors.contact_info_input(
            ["x"] * emails_top, icp["target_departments"], leads_per_domain, True)),
    }
    return {"worst_case_usd": round(sum(parts.values()), 2), "by_stage": parts,
            "session_budget_remaining_usd": round(runner.remaining(), 2),
            "note": "Upper bound at list price. Actors bill per delivered result, so real spend is usually lower."}


@mcp.tool()
@_guard
def source_companies(sources: list[str] | None = None, max_companies: int = 25,
                     max_jobs_per_keyword: int = 25) -> dict[str, Any]:
    """Find companies hiring for the ICP's keywords. sources: indeed_jobs (default), linkedin_jobs. Paid."""
    store, runner = _ctx()
    icp = _icp(store)
    out = pipeline.source_companies(store, runner, icp, sources=sources, max_companies=max_companies,
                                    max_jobs_per_keyword=max_jobs_per_keyword)
    pipeline.score_all(store, icp)
    return out


@mcp.tool()
@_guard
def enrich_companies(company_ids: list[int] | None = None, top: int = 10, use_indeed: bool = True,
                     use_linkedin: bool = True, use_crunchbase: bool = True) -> dict[str, Any]:
    """Add website, firmographics and funding (Indeed employer page, LinkedIn, Crunchbase). Paid."""
    store, runner = _ctx()
    icp = _icp(store)
    out = pipeline.enrich_companies(store, runner, _pick(store, company_ids, top, only_unenriched=True),
                                    use_indeed=use_indeed, use_linkedin=use_linkedin, use_crunchbase=use_crunchbase)
    pipeline.score_all(store, icp)
    return out


@mcp.tool()
@_guard
def find_contacts(company_ids: list[int] | None = None, top: int = 5, per_company: int = 3,
                  use_search: bool = True) -> dict[str, Any]:
    """Named decision-makers matching target_titles. Free from enrichment first, then paid people search."""
    store, runner = _ctx()
    icp = _icp(store)
    out = pipeline.find_contacts(store, runner, icp, _pick(store, company_ids, top), per_company=per_company,
                                 use_search=use_search)
    pipeline.score_all(store, icp)
    return out


@mcp.tool()
@_guard
def find_emails(company_ids: list[int] | None = None, top: int = 5, leads_per_domain: int = 3,
                verify: bool = True, pages_per_domain: int = 10) -> dict[str, Any]:
    """Work emails with a verification verdict, plus the company inbox. Needs a known website. Paid."""
    store, runner = _ctx()
    icp = _icp(store)
    out = pipeline.find_emails(store, runner, icp, company_ids or pipeline.top_ids(store, top, need_domain=True), leads_per_domain=leads_per_domain,
                               verify=verify, pages_per_domain=pages_per_domain)
    pipeline.score_all(store, icp)
    return out


@mcp.tool()
@_guard
def score_leads() -> dict[str, Any]:
    """Re-score every account against the saved ICP. Free and deterministic."""
    store, _ = _ctx()
    return {"scored": pipeline.score_all(store, _icp(store))}


@mcp.tool()
@_guard
def list_leads(min_score: float = 0, limit: int = 25) -> list[dict[str, Any]]:
    """Ranked accounts, one slim line each. Use get_lead for the full record."""
    store, _ = _ctx()
    return [pipeline.lead_summary(store, cid) for cid in store.ranked_company_ids(min_score, limit)]


@mcp.tool()
@_guard
def get_lead(company_id: int) -> dict[str, Any]:
    """Everything known about one account: score reasons, signals, contacts, emails."""
    store, _ = _ctx()
    return pipeline.lead_detail(store, company_id) or {"error": "not_found"}


@mcp.tool()
@_guard
def export_leads(path: str = "~/alphaosint-leads.csv", format: str = "csv", min_score: float = 0,
                 limit: int | None = None) -> dict[str, Any]:
    """Write the ranked leads file (csv, json or xlsx)."""
    store, _ = _ctx()
    return _export(store, path, format, min_score, limit)


@mcp.tool()
@_guard
def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Recent Actor runs with run ids, item counts, estimated and actual cost."""
    store, _ = _ctx()
    return store.list_runs(limit)


@mcp.tool()
@_guard
def get_spend() -> dict[str, Any]:
    """Spend this session and all time, against the session cap."""
    store, runner = _ctx()
    return {"session_usd": round(runner.session_spend(), 4), "all_time_usd": round(store.spend(), 4),
            "session_budget_usd": runner.settings.session_budget_usd, "remaining_usd": round(runner.remaining(), 4)}


def serve() -> None:
    mcp.run()
