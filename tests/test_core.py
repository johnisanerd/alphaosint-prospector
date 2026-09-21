from __future__ import annotations

from datetime import date

import pytest

from alpha_prospector import actors
from alpha_prospector.icp import IcpError, validate_icp
from alpha_prospector.resolve import normalize_domain, normalize_name, same_company
from alpha_prospector.runner import BudgetExceeded, charged_cost
from alpha_prospector.scoring import parse_size_band, score_company


# -- resolve ------------------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://www.Acme.com/about", "acme.com"), ("acme.co.uk", "acme.co.uk"),
    ("http://careers.acme.co.uk/jobs", "acme.co.uk"), ("https://www.linkedin.com/company/acme", None),
    ("", None), (None, None), ("not a url", None),
])
def test_normalize_domain(url, expected):
    assert normalize_domain(url) == expected


def test_normalize_name_strips_legal_suffixes():
    assert normalize_name("Acme, Inc.") == normalize_name("ACME") == "acme"
    assert normalize_name("Smith & Sons Ltd") == "smith and sons"


def test_same_company_fails_closed():
    assert same_company("Acme", "acme.com", "Acme", "https://acme.com")[0]
    assert not same_company("Acme", "acme.com", "Acme", "https://acme.io")[0]  # namesake, different domain
    assert same_company("Acme Inc", None, "Acme", None)[0]
    assert not same_company("Acme", None, "Acme Robotics", "https://acmerobotics.com")[0]


# -- icp ------------------------------------------------------------------------------
def test_icp_validation(icp):
    assert icp["weights"]["fit"] == 35
    with pytest.raises(IcpError):
        validate_icp({"target_titles": ["CEO"]})  # no hiring keywords
    with pytest.raises(IcpError):
        validate_icp({"hiring_keywords": ["x"], "target_titles": ["CEO"], "target_departments": ["wizards"]})
    with pytest.raises(IcpError):
        validate_icp({"hiring_keywords": ["x"], "target_titles": ["CEO"], "typo_field": 1})


# -- actors ----------------------------------------------------------------------------
def test_indeed_window_and_input(icp):
    assert actors.indeed_date_window(1) == "Last 24 hours"
    assert actors.indeed_date_window(10) == "Last 14 days"
    assert actors.indeed_date_window(30) == ""
    run_input = actors.indeed_jobs_input(icp, 20)
    assert run_input["mode"] == "search" and run_input["includeCompanyDetails"] is True
    assert "location" not in run_input


def test_contact_info_input_is_capped():
    run_input = actors.contact_info_input(["https://a.com", "https://b.com"], ["sales"], 3, True, pages_per_domain=500)
    assert run_input["proxyConfig"] == {"useApifyProxy": True}
    assert run_input["maxRequestsPerStartUrl"] == 15 and run_input["maxRequests"] == 30 and run_input["maxDepth"] == 1
    assert run_input["verifyLeadsEnrichmentEmails"] is True
    no_leads = actors.contact_info_input(["https://a.com"], ["sales"], 0, True)
    assert "verifyLeadsEnrichmentEmails" not in no_leads


def test_estimates_are_upper_bounds():
    est = actors.ACTORS["indeed_jobs"].estimate({"keywords": ["a", "b"], "maxResultsPerInput": 10, "includeCompanyDetails": True})
    assert est == pytest.approx(2 * 10 * (0.0038 + 0.0057))


# -- runner ------------------------------------------------------------------------------
def test_budget_guard_blocks_before_any_call(make_runner):
    runner, backend = make_runner(call=0.05)
    with pytest.raises(BudgetExceeded):
        runner.run("crunchbase_company", {"companyNames": ["x"] * 50})
    assert backend.calls == []


def test_session_budget_and_cost_logging(make_runner, store):
    runner, backend = make_runner({"johnvc/crunchbase-company-api": [{"name": "A"}] * 5}, session=0.06, call=1.0)
    result = runner.run("crunchbase_company", {"companyNames": ["x"] * 5})
    assert result.cost == pytest.approx(0.05) and store.spend() == pytest.approx(0.05)
    assert backend.calls[0]["cap"] <= 0.06  # platform-side cap never exceeds the remaining budget
    with pytest.raises(BudgetExceeded):
        runner.run("crunchbase_company", {"companyNames": ["x"] * 5})


def test_charged_cost_tiered():
    info = {"chargedEventCounts": {"lead": 2},
            "pricingInfo": {"pricingPerEvent": {"actorChargeEvents": {"lead": {"eventTieredPricingUsd": {
                "FREE": {"tieredEventPriceUsd": 0.1}, "BRONZE": {"tieredEventPriceUsd": 0.005}}}}}}}
    assert charged_cost(info, "BRONZE") == pytest.approx(0.01)
    assert charged_cost(info, "FREE") == pytest.approx(0.2)
    assert charged_cost({}) is None


# -- scoring -------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("51-200 employees", (51, 200)), ("10,001+ employees", (10001, None)), ("1001-5000", (1001, 5000)), (None, (None, None)),
])
def test_parse_size_band(text, expected):
    assert parse_size_band(text) == expected


def test_score_is_deterministic_and_explained(icp):
    company = {"industry": "Software Development", "employees_min": 51, "employees_max": 200, "size_band": "51-200",
               "country": "US", "enrichment": {"linkedin": {"funding": {"last_round_type": "Series A", "last_round_date": "2026-06-01"}}}}
    signals = [{"type": "hiring", "title": "SDR", "observed_at": "2026-09-18T00:00:00Z", "detail": {"urgent": True}}]
    emails = [{"kind": "person", "verification": "ok"}]
    args = (company, signals, [{"id": 1}], emails, icp, date(2026, 9, 21))
    total, parts, reasons = score_company(*args)
    assert score_company(*args) == (total, parts, reasons)
    assert parts["fit"] == 35 and parts["reachability"] == 10 and parts["funding"] == 15
    assert 0 < total <= 100 and any("Series A" in r for r in reasons)


def test_unknown_data_scores_zero_not_average(icp):
    total, parts, reasons = score_company({"enrichment": {}}, [], [], [], icp, date(2026, 9, 21))
    assert total == 0 and "fit: headcount unknown" in reasons and "funding: not enriched" in reasons


def test_min_charge_cap_floor(make_runner):
    runner, backend = make_runner({"vdrmota/contact-info-scraper": []}, session=2.0)
    runner.run("contact_info", actors.contact_info_input(["https://a.com"], ["sales"], 1, True, 5))
    assert backend.calls[0]["cap"] == 0.50
    poor, backend2 = make_runner(session=0.30)
    with pytest.raises(BudgetExceeded, match="at least"):
        poor.run("contact_info", actors.contact_info_input(["https://a.com"], ["sales"], 1, True, 5))
    assert backend2.calls == []


def test_network_blip_is_retried(monkeypatch):
    from alpha_prospector import runner as r
    monkeypatch.setattr(r.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("dns")
        return "ok"

    assert r._patiently(flaky, "run1") == "ok" and calls["n"] == 3
    with pytest.raises(r.ActorRunError, match="run1"):
        r._patiently(lambda: (_ for _ in ()).throw(ConnectionError("x")), "run1", attempts=2)
