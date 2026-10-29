"""Actor registry: ids, list prices per event, worst-case cost estimators and input builders.

Prices are the published pay-per-event list prices (USD) at the entry tier, taking the higher
of the current and the next scheduled price (checked 2026-10-20). Paid Apify plans pay the same
or less, so estimates are upper bounds. Inputs are built from each Actor's live
input schema; nothing here guesses a field name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

TRACKER = "fpr=9n7kx3"


@dataclass(frozen=True)
class ActorSpec:
    key: str
    actor_id: str
    prices: dict[str, float]
    estimate: Callable[[dict[str, Any]], float]
    min_charge_cap: float = 0.0  # some Actors reject runs whose max charge is below a floor

    @property
    def url(self) -> str:
        return f"https://apify.com/{self.actor_id}?{TRACKER}"


def _n(value: Any) -> int:
    return len(value) if isinstance(value, (list, tuple)) else (1 if value else 0)


# -- estimators (worst case for the given input) -------------------------------
def _est_indeed_jobs(i: dict[str, Any]) -> float:
    per_job = 0.0038 + (0.0057 if i.get("includeCompanyDetails") else 0)
    searches = max(1, _n(i.get("keywords"))) * max(1, _n(i.get("jobType")))
    return searches * int(i.get("maxResultsPerInput", 50)) * per_job


def _est_indeed_company(i: dict[str, Any]) -> float:
    inputs = max(1, _n(i.get("keywords")) + _n(i.get("companyUrls")) + _n(i.get("states")))
    per = 0.00285 if i.get("profileDetail", "full") == "full" else 0.00038
    limit = 1 if i.get("resolveExact") else int(i.get("maxResultsPerInput", 25))
    return inputs * limit * per


def _est_linkedin_jobs(i: dict[str, Any]) -> float:
    return max(_n(i.get("jobUrls")), int(i.get("maxJobs", 25))) * 0.00001


def _est_linkedin_company(i: dict[str, Any]) -> float:
    return _n(i.get("companyUrls")) * 0.00001 + _n(i.get("companyNames")) * (0.00001 + 0.00396)


def _est_crunchbase(i: dict[str, Any]) -> float:
    return (_n(i.get("companyUrls")) + _n(i.get("companyNames"))) * 0.00855


def _est_people_search(i: dict[str, Any]) -> float:
    # The Actor returns a full page of about 10 people even when maxResults is smaller (seen 2026-09-21
    # and 2026-10-29), and bills each one, so estimate at least a page.
    per = 0.0006 + (0.0025 if i.get("enrichProfiles", True) else 0)
    return max(10, int(i.get("maxResults", 25))) * per


def _est_linkedin_profile(i: dict[str, Any]) -> float:
    return _n(i.get("profileUrls")) * 0.00001


def _est_contact_info(i: dict[str, Any]) -> float:
    domains = max(1, _n(i.get("startUrls")))
    pages = domains * int(i.get("maxRequestsPerStartUrl", 20))
    if i.get("maxRequests"):
        pages = min(pages, int(i["maxRequests"]))
    leads = domains * int(i.get("maximumLeadsEnrichmentRecords", 0))
    per_lead = 0.005 + (0.004 if i.get("verifyLeadsEnrichmentEmails") else 0)
    return 0.004 + pages * 0.002 + leads * per_lead


ACTORS: dict[str, ActorSpec] = {
    spec.key: spec
    for spec in (
        ActorSpec("indeed_jobs", "johnvc/indeed-jobs-api",
                  {"job-scraped": 0.0038, "company-details-added": 0.0057}, _est_indeed_jobs),
        ActorSpec("indeed_company", "johnvc/indeed-company-api",
                  {"company-scraped": 0.00285, "company-listed": 0.00038}, _est_indeed_company),
        ActorSpec("linkedin_jobs", "johnvc/linkedin-jobs-api", {"job-scraped": 0.00001}, _est_linkedin_jobs),
        ActorSpec("linkedin_company", "johnvc/linkedin-company-api",
                  {"company-scraped": 0.00001, "company-searched": 0.00396}, _est_linkedin_company),
        ActorSpec("crunchbase_company", "johnvc/crunchbase-company-api",
                  {"company-scraped": 0.00855}, _est_crunchbase),
        ActorSpec("linkedin_people", "johnvc/linkedin-people-search-api",
                  {"person-found": 0.0006, "person-enriched": 0.0025}, _est_people_search),
        ActorSpec("linkedin_profile", "johnvc/linkedin-profile-api",
                  {"profile-scraped": 0.00001}, _est_linkedin_profile),
        ActorSpec("contact_info", "vdrmota/contact-info-scraper",
                  {"scraped-page": 0.002, "lead": 0.005, "email-verification": 0.004}, _est_contact_info,
                  min_charge_cap=0.50),
    )
}


# -- input builders ----------------------------------------------------------------
_INDEED_WINDOWS = ((1, "Last 24 hours"), (3, "Last 3 days"), (7, "Last 7 days"), (14, "Last 14 days"))


def indeed_date_window(days: int) -> str:
    """Smallest Indeed window covering `days`; empty string (any time) beyond 14 days."""
    for limit, label in _INDEED_WINDOWS:
        if days <= limit:
            return label
    return ""


def indeed_jobs_input(icp: dict[str, Any], max_jobs_per_keyword: int) -> dict[str, Any]:
    run_input: dict[str, Any] = {
        "mode": "search",
        "keywords": icp["hiring_keywords"],
        "country": (icp.get("countries") or ["US"])[0],
        "datePosted": indeed_date_window(icp["hiring_recency_days"]),
        "sortBy": "relevance",  # the date window already bounds recency; date sort surfaces loose matches
        "maxResultsPerInput": max_jobs_per_keyword,
        "uniqueJobsOnly": True,
        "includeCompanyDetails": True,  # not charged when the Actor cannot supply them
        "descriptionFormat": "text",
    }
    if icp.get("location"):
        run_input["location"] = icp["location"]
    return run_input


def linkedin_jobs_input(icp: dict[str, Any], keyword: str, max_jobs: int) -> dict[str, Any]:
    days = icp["hiring_recency_days"]
    run_input: dict[str, Any] = {
        "keyword": keyword,
        "country": (icp.get("countries") or ["US"])[0],
        "timeRange": "past-day" if days <= 1 else "past-week" if days <= 7 else "past-month",
        "maxJobs": max_jobs,
    }
    if icp.get("location"):
        run_input["location"] = icp["location"]
    return run_input


def contact_info_input(websites: list[str], departments: list[str], leads_per_domain: int,
                       verify: bool, pages_per_domain: int = 10) -> dict[str, Any]:
    """Crawl is capped in three places because this Actor bills per page, not per email."""
    pages_per_domain = max(1, min(pages_per_domain, 15))
    run_input: dict[str, Any] = {
        "startUrls": [{"url": url} for url in websites],
        "proxyConfig": {"useApifyProxy": True},
        "maxRequestsPerStartUrl": pages_per_domain,
        "maxRequests": pages_per_domain * len(websites),
        "maxDepth": 1,
        "sameDomain": True,
        "mergeContacts": True,
        "considerChildFrames": False,
        "useBrowser": False,
        "maximumLeadsEnrichmentRecords": max(0, leads_per_domain),
    }
    if leads_per_domain > 0:
        if departments:
            run_input["leadsEnrichmentDepartments"] = departments
        run_input["verifyLeadsEnrichmentEmails"] = bool(verify)
    return run_input
