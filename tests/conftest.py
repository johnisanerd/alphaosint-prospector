from __future__ import annotations

import pytest

from alpha_prospector.config import Settings
from alpha_prospector.db import Store
from alpha_prospector.icp import validate_icp
from alpha_prospector.runner import Runner


class FakeBackend:
    """Returns canned dataset items per actor id and records every call."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, actor_id, run_input, max_items, max_charge_usd):
        self.calls.append({"actor": actor_id, "input": run_input, "cap": max_charge_usd})
        items = self.responses.get(actor_id, [])
        items = items(run_input) if callable(items) else items
        info = {"id": f"run{len(self.calls)}", "status": "SUCCEEDED", "chargedEventCounts": {"e": len(items)},
                "pricingInfo": {"pricingPerEvent": {"actorChargeEvents": {"e": {"eventPriceUsd": 0.01}}}}}
        return info, items


@pytest.fixture
def icp():
    return validate_icp({
        "name": "test", "industries": ["software"], "employee_range": [50, 500], "countries": ["US"],
        "hiring_keywords": ["sales development representative"], "hiring_recency_days": 14,
        "target_titles": ["VP Sales", "Head of Sales"], "target_departments": ["sales"],
        "exclude_companies": ["Blocked Inc"],
    })


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture
def make_runner(store):
    def _make(responses=None, session=2.0, call=1.0):
        backend = FakeBackend(responses)
        return Runner(store, Settings("tok", session, call), backend=backend), backend
    return _make
