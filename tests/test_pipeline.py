from __future__ import annotations

import csv

from alpha_prospector import pipeline
from alpha_prospector.export import export_leads

JOBS = [
    {"result_type": "job", "jobId": "j1", "jobTitle": "Sales Development Representative", "companyName": "Acme Inc",
     "companyWebsite": "https://www.acme.com", "companyIndustry": "Software Development", "companySize": "51 to 200",
     "datePosted": "2026-09-18T00:00:00Z", "country": "US", "isUrgentlyHiring": True},
    {"result_type": "job", "jobId": "j2", "jobTitle": "Senior Sales Development Representative", "companyName": "ACME",
     "companyWebsite": "http://acme.com/careers", "datePosted": "2026-09-17T00:00:00Z"},
    {"result_type": "job", "jobId": "j3", "jobTitle": "Sales Development Representative", "companyName": "TalentBridge",
     "companyIndustry": "Staffing", "companyWebsite": "https://talentbridge.com"},
    {"result_type": "job", "jobId": "j4", "jobTitle": "Sales Development Representative", "companyName": "Blocked Inc"},
    {"result_type": "job", "jobId": "j5", "jobTitle": "Sales Development Representative", "companyName": "Beta Labs", "companyWebsite": "https://betalabs.io"},
    {"result_type": "job", "jobId": "j6", "jobTitle": "Inside Sales Representative - Flooring", "companyName": "All About Floors"},
    {"result_type": "error", "error_message": "page could not be read"},
]


def _source(store, make_runner, icp, extra=None):
    runner, backend = make_runner({"johnvc/indeed-jobs-api": JOBS, **(extra or {})})
    summary = pipeline.source_companies(store, runner, icp)
    return runner, backend, summary


def test_source_dedupes_by_domain_and_applies_exclusions(store, make_runner, icp):
    _, _, summary = _source(store, make_runner, icp)
    names = sorted(c["name"] for c in store.list_companies())
    assert names == ["Acme Inc", "Beta Labs"]
    assert summary["new_hiring_signals"] == 3 and summary["error_rows"] == 1 and summary["off_title_jobs_ignored"] == 1
    assert "TalentBridge" in summary["dropped"] and "Blocked Inc" in summary["dropped"]
    acme = store.find_company("Acme", "acme.com")
    assert len(store.signals(acme["id"], "hiring")) == 2


def test_source_keeps_best_fit_not_first_seen(store, make_runner, icp):
    junk = [{"result_type": "job", "jobId": f"x{i}", "jobTitle": "Sales Development Representative", "companyName": f"Diner {i}",
             "companyIndustry": "Restaurants", "companySize": "2 to 10"} for i in range(5)]
    runner, _ = make_runner({"johnvc/indeed-jobs-api": junk + JOBS})
    pipeline.source_companies(store, runner, icp, max_companies=1)
    assert [c["name"] for c in store.list_companies()] == ["Acme Inc"]


def test_staffing_firm_caught_by_name(store, make_runner, icp):
    runner, _ = make_runner({"johnvc/indeed-jobs-api": [
        {"result_type": "job", "jobId": "s1", "jobTitle": "Sales Development Representative", "companyName": "Quality Staffing Services"}]})
    out = pipeline.source_companies(store, runner, icp)
    assert out["companies"] == 0 and "Quality Staffing Services" in out["dropped"]


def test_source_is_idempotent(store, make_runner, icp):
    _source(store, make_runner, icp)
    _, _, again = _source(store, make_runner, icp)
    assert again["new_hiring_signals"] == 0 and len(store.list_companies()) == 2


def test_enrich_drops_namesake_with_other_domain(store, make_runner, icp):
    runner, _, _ = _source(store, make_runner, icp, {
        "johnvc/linkedin-company-api": [
            {"result_type": "company", "requestedName": "Acme Inc", "name": "Acme", "website": "https://acme.com",
             "companySize": "51-200 employees", "industries": ["Software Development"], "publicUrl": "https://www.linkedin.com/company/acme",
             "funding": {"last_round_type": "Series A", "last_round_date": "2026-06-01"}},
            {"result_type": "company", "requestedName": "Beta Labs", "name": "Beta Labs", "website": "https://betalabs.de"},
        ],
        "johnvc/crunchbase-company-api": lambda i: [
            {"result_type": "company", "searchTerm": "acme.com", "name": "Acme", "website": "https://www.acme.com",
             "numFundingRounds": 2, "contactEmail": "hello@acme.com",
             "contacts": [{"name": "Dana Reyes", "title": "VP of Sales", "linkedinId": "dana-reyes"},
                          {"name": "Sam Poe", "title": "Staff Engineer"}]},
        ],
    })
    ids = [c["id"] for c in store.list_companies()]
    out = pipeline.enrich_companies(store, runner, ids)
    assert out["matched"] == {"indeed": 0, "linkedin": 1, "crunchbase": 1}
    assert [m["company"] for m in out["mismatches_dropped"]] == ["Beta Labs"]
    beta = store.find_company("Beta Labs", None)
    assert "linkedin" not in store.get_company(beta["id"])["enrichment"]

    acme_id = store.find_company("Acme", "acme.com")["id"]
    found = pipeline.find_contacts(store, runner, icp, [acme_id], use_search=False)
    assert found["contacts_added"] == 1 and store.contacts(acme_id)[0]["full_name"] == "Dana Reyes"


def test_indeed_company_supplies_the_join_domain(store, make_runner, icp):
    runner, backend = make_runner({
        "johnvc/indeed-jobs-api": [{"result_type": "job", "jobId": "n1", "jobTitle": "Sales Development Representative",
                                    "companyName": "Nimbus"}],
        "johnvc/indeed-company-api": [{"result_type": "company", "searchInput": "Nimbus", "companyName": "Nimbus Inc",
                                       "website": "https://nimbus.io", "industry": "Software Development",
                                       "employeesMin": 51, "employeesMax": 200, "companySize": "51 to 200"}],
        "johnvc/crunchbase-company-api": lambda i: [{"result_type": "company", "searchTerm": i["companyNames"][0],
                                                     "name": "Nimbus", "website": "https://nimbus.io", "numFundingRounds": 1}],
    })
    pipeline.source_companies(store, runner, icp)
    cid = store.list_companies()[0]["id"]
    out = pipeline.enrich_companies(store, runner, [cid], use_linkedin=False)
    company = store.get_company(cid)
    assert company["domain"] == "nimbus.io" and company["employees_max"] == 200 and out["matched"]["indeed"] == 1
    crunchbase_call = [c for c in backend.calls if "crunchbase" in c["actor"]][0]
    assert crunchbase_call["input"]["companyNames"] == ["nimbus.io"]  # looked up by domain, not by name


def test_people_search_rejects_wrong_employer(store, make_runner, icp):
    runner, _, _ = _source(store, make_runner, icp, {"johnvc/linkedin-people-search-api": [
        {"resultType": "person", "fullName": "Lee Wong", "headline": "VP Sales at Acme", "currentCompany": "Acme, Inc."},
        {"resultType": "person", "fullName": "Old Timer", "headline": "VP Sales", "currentCompany": "Globex"},
    ]})
    acme_id = store.find_company("Acme", "acme.com")["id"]
    out = pipeline.find_contacts(store, runner, icp, [acme_id], per_company=1)
    assert out["contacts_added"] == 1 and out["rejected_wrong_employer"] >= 1
    assert [c["full_name"] for c in store.contacts(acme_id)] == ["Lee Wong"]


def test_emails_scored_and_exported(store, make_runner, icp, tmp_path):
    runner, backend, _ = _source(store, make_runner, icp, {"vdrmota/contact-info-scraper": [
        {"domain": "acme.com", "emails": ["info@acme.com", "abc123@sentry.io"],
         "leadsEnrichment": [{"fullName": "Dana Reyes", "jobTitle": "VP Sales", "email": "dana@acme.com",
                              "emailVerification": {"result": "ok"}}]},
        {"domain": "unrelated.com", "emails": ["x@unrelated.com"]},
    ]})
    ids = [c["id"] for c in store.list_companies()]
    out = pipeline.find_emails(store, runner, icp, ids)
    assert out["person_emails"] == 1 and out["company_emails"] == 1 and out["off_domain_dropped"] == 1
    sent = backend.calls[-1]["input"]
    assert sent["maxDepth"] == 1 and len(sent["startUrls"]) == 2

    pipeline.score_all(store, icp)
    result = export_leads(store, tmp_path / "leads.csv")
    rows = list(csv.DictReader((tmp_path / "leads.csv").open()))
    assert result["rows"] == len(rows) == 2 and rows[0]["company"] == "Acme Inc"
    assert rows[0]["email"] == "dana@acme.com" and rows[0]["email_verification"] == "ok"
    assert float(rows[0]["score"]) > float(rows[1]["score"])


def test_mcp_tools_register():
    import asyncio

    from alpha_prospector.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"set_icp", "estimate_cost", "source_companies", "enrich_companies", "find_contacts", "find_emails",
            "score_leads", "list_leads", "get_lead", "export_leads", "list_runs", "get_spend"} <= names


def test_parent_brand_page_and_bad_emails_are_not_adopted(store, make_runner, icp):
    runner, _ = make_runner({
        "johnvc/indeed-jobs-api": [{"result_type": "job", "jobId": "a1", "jobTitle": "Sales Development Representative",
                                    "companyName": "Jackson Mitchell Agency", "companyUrl": "https://www.indeed.com/cmp/Farmers"}],
        "johnvc/indeed-company-api": [{"result_type": "company", "sourceInput": "https://www.indeed.com/cmp/Farmers",
                                       "companyName": "Farmers Insurance", "website": "https://farmers.com"}],
    })
    pipeline.source_companies(store, runner, icp)
    cid = store.list_companies()[0]["id"]
    out = pipeline.enrich_companies(store, runner, [cid], use_linkedin=False, use_crunchbase=False)
    assert store.get_company(cid)["domain"] is None and out["mismatches_dropped"][0]["source"] == "indeed"

    store.add_email(cid, "bad@x.com", kind="person", verification="invalid")
    store.add_email(cid, "maybe@x.com", kind="person", verification="catch_all")
    assert [e["address"] for e in store.emails(cid)] == ["maybe@x.com"]
    assert len(store.emails(cid, usable_only=False)) == 2
