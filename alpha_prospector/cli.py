"""CLI: `alpha-prospector serve` (MCP server), `run` (whole pipeline), `export`, `stats`."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import click

from . import pipeline
from .config import db_path, load_settings
from .db import Store
from .export import export_leads
from .icp import IcpError, validate_icp
from .runner import ActorRunError, BudgetExceeded, Runner


@click.group()
def main() -> None:
    """Alpha OSINT Prospector."""


@main.command()
def serve() -> None:
    """Start the MCP server on stdio."""
    from .mcp_server import serve as _serve

    _serve()


@main.command()
@click.option("--icp", "icp_path", type=click.Path(exists=True, dir_okay=False), help="ICP JSON file. Omit to reuse the saved one.")
@click.option("--source", "sources", multiple=True, default=["indeed_jobs"], show_default=True)
@click.option("--max-companies", default=10, show_default=True)
@click.option("--max-jobs", default=25, show_default=True, help="Jobs per hiring keyword.")
@click.option("--enrich-top", default=10, show_default=True)
@click.option("--contacts-top", default=5, show_default=True)
@click.option("--emails-top", default=3, show_default=True)
@click.option("--budget", type=float, help="Session budget in USD for this run.")
@click.option("--out", default="leads.csv", show_default=True)
def run(icp_path, sources, max_companies, max_jobs, enrich_top, contacts_top, emails_top, budget, out) -> None:
    """Source, enrich, find emails and contacts, score, export."""
    store = Store(db_path())
    settings = load_settings()
    if budget:
        settings = replace(settings, session_budget_usd=budget, call_budget_usd=max(settings.call_budget_usd, budget))
    runner = Runner(store, settings)
    try:
        if icp_path:
            store.set_icp(validate_icp(json.loads(Path(icp_path).read_text())))
        icp = store.get_icp()
        if not icp:
            raise IcpError("No ICP saved. Pass --icp path/to/icp.json")
        steps = [
            ("source", lambda: pipeline.source_companies(store, runner, icp, sources=list(sources),
                                                         max_companies=max_companies, max_jobs_per_keyword=max_jobs)),
            ("enrich", lambda: (pipeline.score_all(store, icp),
                                pipeline.enrich_companies(store, runner, store.ranked_company_ids(limit=enrich_top)))[1]),
            ("emails", lambda: (pipeline.score_all(store, icp),
                                pipeline.find_emails(store, runner, icp, pipeline.top_ids(store, emails_top, need_domain=True)))[1]),
            ("contacts", lambda: (pipeline.score_all(store, icp),
                                  pipeline.find_contacts(store, runner, icp, store.ranked_company_ids(limit=contacts_top)))[1]),
        ]
        for name, step in steps:
            click.echo(f"[{name}] {json.dumps(step(), default=str)}")
    except (BudgetExceeded, ActorRunError, IcpError, ValueError) as exc:
        click.echo(f"Stopped: {exc}", err=True)
    finally:
        if store.get_icp():
            pipeline.score_all(store, store.get_icp())
            click.echo(json.dumps(export_leads(store, out)))
        click.echo(f"Spend this run: ${runner.session_spend():.4f}")


@main.command()
@click.option("--out", default="leads.csv", show_default=True)
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json", "xlsx"]), show_default=True)
@click.option("--min-score", default=0.0, show_default=True)
def export(out, fmt, min_score) -> None:
    """Write the ranked leads file."""
    click.echo(json.dumps(export_leads(Store(db_path()), out, fmt, min_score)))


@main.command()
def stats() -> None:
    """Counts, spend and recent runs."""
    store = Store(db_path())
    click.echo(json.dumps({"companies": len(store.list_companies()), "all_time_spend_usd": round(store.spend(), 4),
                           "recent_runs": store.list_runs(10)}, indent=2))
