"""The single choke point for paid Actor runs.

Every run is estimated first, checked against a per-call and a per-session budget in code,
started with a platform-side charge cap, and logged with its cost. Upstream error text is
never passed through; callers get a short, generic message plus the run id.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from .actors import ACTORS, ActorSpec
from .config import Settings
from .db import Store, now


class BudgetExceeded(RuntimeError):
    pass


class ActorRunError(RuntimeError):
    pass


@dataclass
class RunResult:
    actor: str
    run_id: str | None
    status: str
    items: list[dict[str, Any]]
    est_cost: float
    cost: float


class Backend(Protocol):
    """What the runner needs from Apify. Tests swap in a fake."""

    def run(self, actor_id: str, run_input: dict[str, Any], max_items: int | None,
            max_charge_usd: float) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...


class ApifyBackend:
    def __init__(self, token: str):
        from apify_client import ApifyClient

        self.client = ApifyClient(token)

    def run(self, actor_id, run_input, max_items, max_charge_usd):
        started = None
        for attempt in range(3):
            try:
                # Retrying start() is safe: if it raised, no run was created.
                started = self.client.actor(actor_id).start(
                    run_input=run_input,
                    max_items=max_items,
                    max_total_charge_usd=Decimal(str(round(max_charge_usd, 4))),
                )
                break
            except Exception as exc:  # noqa: BLE001
                from apify_client.errors import ApifyApiError

                if isinstance(exc, ApifyApiError) and 400 <= (exc.status_code or 0) < 500 and exc.status_code != 429:
                    # The platform's own validation message is safe to show and not worth retrying.
                    raise ActorRunError(f"Apify rejected the {actor_id} run: {str(exc)[:200]}") from None
                if attempt == 2:
                    raise ActorRunError(f"Could not start {actor_id}. Check the Apify token and plan.") from None
                time.sleep(2 ** attempt)
        finished = _patiently(lambda: self.client.run(started.id).wait_for_finish(), started.id) or started
        info = finished.model_dump(by_alias=True, mode="json")
        items: list[dict[str, Any]] = []
        dataset_id = finished.default_dataset_id
        offset = 0
        while dataset_id:
            page = _patiently(lambda: self.client.dataset(dataset_id).list_items(offset=offset, limit=1000, clean=True),
                              started.id)
            items.extend(page.items)
            offset += len(page.items)
            if not page.items or offset >= (page.total or 0):
                break
        return info, items


def _patiently(call, run_id: str, attempts: int = 5):
    """Reads are idempotent, so a network blip while a paid run is in flight is retried, not fatal."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception:  # noqa: BLE001
            if attempt == attempts - 1:
                raise ActorRunError(
                    f"Lost contact with Apify while reading run {run_id}. The run itself continues and is "
                    "capped; check it in the Apify Console, then retry this step.") from None
            time.sleep(min(30, 3 * 2 ** attempt))


def charged_cost(info: dict[str, Any], tier: str = "BRONZE") -> float | None:
    """Sum charged events x event price from the run's own pricing info. None if unknown."""
    counts = info.get("chargedEventCounts") or {}
    events = ((info.get("pricingInfo") or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    if not counts or not events:
        return None
    total = 0.0
    for name, count in counts.items():
        event = events.get(name) or {}
        price = event.get("eventPriceUsd")
        if price is None:
            tiers = event.get("eventTieredPricingUsd") or {}
            chosen = tiers.get(tier) or tiers.get("FREE") or next(iter(tiers.values()), None)
            price = (chosen or {}).get("tieredEventPriceUsd")
        if price is None:
            return None
        total += float(price) * int(count or 0)
    return round(total, 6)


class Runner:
    def __init__(self, store: Store, settings: Settings, backend: Backend | None = None):
        self.store = store
        self.settings = settings
        self._backend = backend
        self.session_started = now()
        self.tier = os.environ.get("PROSPECTOR_APIFY_TIER", "BRONZE").upper()

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            if not self.settings.has_token:
                raise ActorRunError("APIFY_TOKEN is not set. Add it to ~/.alphaosint/.env and restart.")
            self._backend = ApifyBackend(self.settings.apify_token)
        return self._backend

    def session_spend(self) -> float:
        return self.store.spend(since=self.session_started)

    def remaining(self) -> float:
        return max(0.0, self.settings.session_budget_usd - self.session_spend())

    def estimate(self, key: str, run_input: dict[str, Any]) -> float:
        return round(ACTORS[key].estimate(run_input), 4)

    def check_budget(self, est: float) -> None:
        if est > self.settings.call_budget_usd:
            raise BudgetExceeded(
                f"Estimated ${est:.2f} is over the per-call cap of ${self.settings.call_budget_usd:.2f}. "
                "Lower the limits, or raise PROSPECTOR_CALL_BUDGET_USD in ~/.alphaosint/.env."
            )
        if est > self.remaining():
            raise BudgetExceeded(
                f"Estimated ${est:.2f} is over the remaining session budget of ${self.remaining():.2f} "
                f"(cap ${self.settings.session_budget_usd:.2f}). Raise PROSPECTOR_SESSION_BUDGET_USD to continue."
            )

    def run(self, key: str, run_input: dict[str, Any], max_items: int | None = None) -> RunResult:
        spec: ActorSpec = ACTORS[key]
        est = self.estimate(key, run_input)
        self.check_budget(est)
        # Platform-side cap: the run cannot charge more than the estimate plus a small margin.
        cap = min(self.remaining(), max(0.05, est * 1.25))
        if spec.min_charge_cap > cap:
            if spec.min_charge_cap > self.remaining():
                raise BudgetExceeded(
                    f"{spec.actor_id} only accepts runs with a charge cap of at least ${spec.min_charge_cap:.2f}, "
                    f"but ${self.remaining():.2f} of the session budget is left. The input limits keep the real "
                    f"cost near ${est:.2f}; raise PROSPECTOR_SESSION_BUDGET_USD to run it.")
            cap = spec.min_charge_cap
        try:
            info, items = self.backend.run(spec.actor_id, run_input, max_items, cap)
        except ActorRunError:
            self.store.log_run(spec.actor_id, None, "START_FAILED", 0, est, 0.0, run_input)
            raise
        status = str(info.get("status") or "UNKNOWN")
        cost = charged_cost(info, self.tier)
        if cost is None:
            cost = float(info.get("usageTotalUsd") or 0.0) or (est if items else 0.0)
        run_id = info.get("id")
        self.store.log_run(spec.actor_id, run_id, status, len(items), est, cost, run_input)
        if status != "SUCCEEDED" and not items:
            raise ActorRunError(f"{spec.actor_id} run {run_id} ended with status {status} and no results.")
        return RunResult(spec.actor_id, run_id, status, items, est, cost)
