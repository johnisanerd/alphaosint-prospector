"""Paths, secrets and budget settings. Everything lives under ~/.alphaosint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_SESSION_BUDGET_USD = 2.00
DEFAULT_CALL_BUDGET_USD = 1.00


def home() -> Path:
    path = Path(os.environ.get("ALPHAOSINT_HOME", Path.home() / ".alphaosint"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return home() / "prospector.db"


@dataclass(frozen=True)
class Settings:
    apify_token: str | None
    session_budget_usd: float
    call_budget_usd: float

    @property
    def has_token(self) -> bool:
        return bool(self.apify_token)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def load_settings() -> Settings:
    load_dotenv(home() / ".env")
    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    return Settings(
        apify_token=token or None,
        session_budget_usd=_float_env("PROSPECTOR_SESSION_BUDGET_USD", DEFAULT_SESSION_BUDGET_USD),
        call_budget_usd=_float_env("PROSPECTOR_CALL_BUDGET_USD", DEFAULT_CALL_BUDGET_USD),
    )
