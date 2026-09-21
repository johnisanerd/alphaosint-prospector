"""The prospecting pipeline: source -> enrich -> contacts -> emails -> score.

Each stage reads and writes the Store, so stages can be run separately, repeated, or resumed.
Every function returns a small summary dict (counts, drops with reasons, run ids, cost).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import actors
from .db import Store
from .resolve import normalize_domain, normalize_name, same_company
from .runner import Runner, RunResult
from .scoring import _fit, parse_size_band, score_company

FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me", "protonmail.com"}
LEAD_LIST_KEYS = ("leadsEnrichment", "leads", "businessLeads")


def _on_domain(address: str, domain: str | None) -> bool:
    mail_domain = str(address).rsplit("@", 1)[-1].lower()
    return bool(domain) and (mail_domain == domain or mail_domain in FREE_MAIL)


def _is_error(row: dict[str, Any]) -> bool:
    kind = row.get("result_type") or row.get("resultType")
    return kind == "error" or bool(row.get("error_message") or row.get("errorMessage"))


def _run_meta(result: RunResult) -> dict[str, Any]:
    return {"actor": result.actor, "run_id": result.run_id, "items": len(result.items),
            "estimated_usd": result.est_cost, "cost_usd": round(result.cost, 4)}


def title_matches(title: str | None, targets: list[str]) -> bool:
    text = f" {normalize_name(title)} "
    if not text.strip():
        return False
    for target in targets:
        words = normalize_name(target).split()
        if words and all(f" {w} " in text for w in words):
            return True
    return False


def _excluded(name: str, domain: str | None, industry: str | None, icp: dict[str, Any]) -> str | None:
    if normalize_name(name) in {normalize_name(n) for n in icp["exclude_companies"]}:
        return "excluded company"
    if domain and domain in {normalize_domain(d) or d.lower() for d in icp["exclude_domains"]}:
        return "excluded domain"
    low = f"{industry or ''} {name}".lower()  # industry is often blank; agencies usually say so in the name
    for bad in icp["exclude_industries"]:
        if bad.lower() in low:
            return f"excluded industry ({industry or name})"
    return None


# -- 1. source ---------------------------------------------------------------------
def source_companies(store: Store, runner: Runner, icp: dict[str, Any], *, sources: list[str] | None = None,
                     max_companies: int = 25, max_jobs_per_keyword: int = 25) -> dict[str, Any]:
    sources = sources or ["indeed_jobs"]
    unknown = set(sources) - {"indeed_jobs", "linkedin_jobs"}
    if unknown:
        raise ValueError(f"Unknown sources {sorted(unknown)}. Use indeed_jobs and/or linkedin_jobs.")
    runs, dropped, seen, new_signals, errors, off_title = [], {}, {}, 0, 0, 0

    def take(name: str, domain: str | None, industry: str | None) -> bool:
        key = domain or normalize_name(name)
        if key in seen:
            return True
        reason = _excluded(name, domain, industry, icp)
        if reason:
            dropped[name] = reason
            return False
        if len(seen) >= max_companies:
            return False
        seen[key] = name
        return True

    if "indeed_jobs" in sources:
        result = runner.run("indeed_jobs", actors.indeed_jobs_input(icp, max_jobs_per_keyword))
        runs.append(_run_meta(result))
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in result.items:
            if _is_error(row) or not row.get("companyName"):
                errors += _is_error(row)
                continue
            if not title_matches(row.get("jobTitle"), icp["hiring_keywords"]):
                off_title += 1  # job boards match loosely; "Flooring Sales Rep" is not an SDR signal
                continue
            key = normalize_domain(row.get("companyWebsite")) or normalize_name(row["companyName"])
            groups.setdefault(key, []).append(row)

        def prelim(rows: list[dict[str, Any]]) -> tuple[float, int]:
            # A job search returns every employer using the title. Keep the best ICP fits, not the first N.
            head = next((r for r in rows if r.get("companyIndustry") or r.get("companySize")), rows[0])
            lo, hi = parse_size_band(head.get("companySize"))
            fit, _ = _fit({"industry": head.get("companyIndustry"), "description": head.get("companyDescription"),
                           "employees_min": lo, "employees_max": hi, "size_band": head.get("companySize"),
                           "country": icp["countries"][0] if icp["countries"] else None}, icp)
            return fit, len(rows)

        for rows in sorted(groups.values(), key=prelim, reverse=True):
            head = next((r for r in rows if r.get("companyWebsite")), rows[0])
            name, domain = head["companyName"], normalize_domain(head.get("companyWebsite"))
            industry = next((r["companyIndustry"] for r in rows if r.get("companyIndustry")), None)
            if not take(name, domain, industry):
                continue
            for row in rows:
                lo, hi = parse_size_band(row.get("companySize"))
                country = row.get("country") if len(str(row.get("country") or "")) == 2 else icp["countries"][0] if icp["countries"] else None
                cid = store.upsert_company(
                    name, domain, source="indeed_jobs", website=row.get("companyWebsite"),
                    industry=row.get("companyIndustry"), size_band=row.get("companySize"), employees_min=lo,
                    employees_max=hi, hq=row.get("companyHeadquarters"), country=country,
                    description=row.get("companyDescription"), indeed_url=row.get("companyUrl"))
                new_signals += store.add_signal(
                    cid, "hiring", row.get("jobTitle") or "Open role", str(row.get("jobId") or row.get("jobUrl")),
                    detail={"url": row.get("jobUrl"), "location": row.get("location"),
                            "urgent": bool(row.get("isUrgentlyHiring")), "multiple": bool(row.get("isHiringMultiple")),
                            "keyword": row.get("searchKeyword")},
                    observed_at=row.get("datePosted"), source_actor=result.actor, run_id=result.run_id)

    if "linkedin_jobs" in sources:
        for keyword in icp["hiring_keywords"]:
            result = runner.run("linkedin_jobs", actors.linkedin_jobs_input(icp, keyword, max_jobs_per_keyword))
            runs.append(_run_meta(result))
            for row in result.items:
                if _is_error(row) or not row.get("companyName"):
                    errors += _is_error(row)
                    continue
                if not title_matches(row.get("title"), icp["hiring_keywords"]):
                    off_title += 1
                    continue
                industry = ", ".join(row["industries"]) if isinstance(row.get("industries"), list) else row.get("industries")
                if not take(row["companyName"], None, industry):
                    continue
                cid = store.upsert_company(row["companyName"], None, source="linkedin_jobs", industry=industry,
                                           linkedin_url=row.get("companyUrl"), country=row.get("countryCode"))
                new_signals += store.add_signal(
                    cid, "hiring", row.get("title") or "Open role", str(row.get("jobId") or row.get("jobUrl")),
                    detail={"url": row.get("jobUrl"), "location": row.get("location"), "keyword": keyword},
                    observed_at=row.get("postedDate"), source_actor=result.actor, run_id=result.run_id)

    return {"companies": len(seen), "new_hiring_signals": new_signals, "dropped": dropped,
            "off_title_jobs_ignored": off_title, "error_rows": errors, "runs": runs}


# -- 2. enrich ----------------------------------------------------------------------
def _set_domain(store: Store, cid: int, website: str | None) -> None:
    domain = normalize_domain(website)
    if not domain:
        return
    try:
        store.conn.execute("UPDATE companies SET domain = ?, website = COALESCE(website, ?) WHERE id = ? AND domain IS NULL",
                           (domain, website, cid))
        store.conn.commit()
    except sqlite3.IntegrityError:
        store.conn.rollback()  # another account already owns this domain; leave both untouched


def enrich_companies(store: Store, runner: Runner, company_ids: list[int], *, use_indeed: bool = True,
                     use_linkedin: bool = True, use_crunchbase: bool = True) -> dict[str, Any]:
    companies = [c for c in (store.get_company(i) for i in company_ids) if c]
    runs, mismatches, matched = [], [], {"indeed": 0, "linkedin": 0, "crunchbase": 0}

    # Indeed's employer page goes first: it is the cheapest source and usually supplies the website,
    # which is the join key that keeps the LinkedIn and Crunchbase lookups honest.
    todo = [c for c in companies if not c["domain"] or not c["industry"]]
    if use_indeed and todo:
        for mode, field, group in (("url", "companyUrls", [c for c in todo if c["indeed_url"]]),
                                   ("keyword", "keywords", [c for c in todo if not c["indeed_url"]])):
            if not group:
                continue
            by_input = {(c["indeed_url"] if mode == "url" else c["name"]): c for c in group}
            result = runner.run("indeed_company", {
                "mode": mode, field: list(by_input), "country": "US", "resolveExact": True,
                "maxResultsPerInput": 1, "profileDetail": "full", "uniqueCompaniesOnly": True})
            runs.append(_run_meta(result))
            for row in result.items:
                if _is_error(row) or row.get("result_type") not in (None, "company"):
                    continue
                company = by_input.get(row.get("searchInput") or "") or by_input.get(row.get("sourceInput") or "")
                if not company:
                    continue
                # The page a job links to can be the parent brand (an insurance agent's page is the carrier's).
                # Adopt its website only when the employer name itself matches.
                names_match = normalize_name(row.get("companyName")) == company["norm_name"]
                row_domain = normalize_domain(row.get("website"))
                if not names_match or (company["domain"] and row_domain and row_domain != company["domain"]):
                    mismatches.append({"company": company["name"], "source": "indeed", "got": row.get("companyName"),
                                       "reason": "employer page belongs to a different name or domain"})
                    continue
                lo, hi = row.get("employeesMin"), row.get("employeesMax")
                if lo is None:
                    lo, hi = parse_size_band(row.get("companySize"))
                store.upsert_company(company["name"], company["domain"], website=row.get("website"),
                                     industry=row.get("industry"), size_band=row.get("companySize"),
                                     employees_min=lo, employees_max=hi, hq=row.get("headquarters"),
                                     country=row.get("countryCode"), description=row.get("description"),
                                     indeed_url=row.get("companyUrl"))
                _set_domain(store, company["id"], row.get("website"))
                store.merge_enrichment(company["id"], "indeed", {k: row.get(k) for k in (
                    "overallRating", "reviewsCount", "jobsCount", "foundedYear", "ceoName", "revenue")})
                matched["indeed"] += 1
        companies = [c for c in (store.get_company(c["id"]) for c in companies) if c]

    if use_linkedin and companies:
        by_url = {c["linkedin_url"].rstrip("/").lower(): c for c in companies if c["linkedin_url"]}
        by_name = {c["name"]: c for c in companies if not c["linkedin_url"]}
        result = runner.run("linkedin_company", {k: v for k, v in {
            "companyUrls": [c["linkedin_url"] for c in by_url.values()], "companyNames": list(by_name)}.items() if v})
        runs.append(_run_meta(result))
        for row in result.items:
            if _is_error(row):
                continue
            company = by_name.get(row.get("requestedName") or "") or by_url.get(str(row.get("publicUrl") or "").rstrip("/").lower())
            if not company:
                continue
            trusted = company["linkedin_url"] is not None  # a URL we already held is an exact reference
            ok, why = (True, "url reference") if trusted else same_company(company["name"], company["domain"], row.get("name"), row.get("website"))
            if not ok:
                mismatches.append({"company": company["name"], "source": "linkedin", "got": row.get("name"), "reason": why})
                continue
            lo, hi = parse_size_band(row.get("companySize"))
            industries = row.get("industries") or []
            store.upsert_company(company["name"], company["domain"], industry=industries[0] if industries else None,
                                 size_band=row.get("companySize"), employees_min=lo, employees_max=hi,
                                 hq=row.get("headquarters"), description=row.get("description"),
                                 linkedin_url=row.get("publicUrl"), crunchbase_url=row.get("crunchbaseUrl"),
                                 country=(row.get("countryCodes") or [None])[0], website=row.get("website"))
            _set_domain(store, company["id"], row.get("website"))
            store.merge_enrichment(company["id"], "linkedin", {k: row.get(k) for k in (
                "followers", "employeesInLinkedin", "funding", "specialties", "industries", "organizationType")})
            matched["linkedin"] += 1
        companies = [c for c in (store.get_company(c["id"]) for c in companies) if c]

    if use_crunchbase and companies:
        by_url = {c["crunchbase_url"].rstrip("/").lower(): c for c in companies if c["crunchbase_url"]}
        by_term = {(c["domain"] or c["name"]): c for c in companies if not c["crunchbase_url"]}
        result = runner.run("crunchbase_company", {k: v for k, v in {
            "companyUrls": [c["crunchbase_url"] for c in by_url.values()], "companyNames": list(by_term)}.items() if v})
        runs.append(_run_meta(result))
        for row in result.items:
            if _is_error(row):
                continue
            company = by_term.get(row.get("searchTerm") or "") or by_url.get(str(row.get("companyUrl") or "").rstrip("/").lower())
            if not company:
                continue
            ok, why = same_company(company["name"], company["domain"], row.get("name"), row.get("website"))
            if not ok:
                mismatches.append({"company": company["name"], "source": "crunchbase", "got": row.get("name"), "reason": why})
                continue
            lo, hi = parse_size_band(row.get("employeeCount"))
            store.upsert_company(company["name"], company["domain"], size_band=row.get("employeeCount"),
                                 employees_min=lo, employees_max=hi, hq=row.get("hqLocation"),
                                 crunchbase_url=row.get("companyUrl"), description=row.get("description"),
                                 website=row.get("website"))
            _set_domain(store, company["id"], row.get("website"))
            payload = {k: row.get(k) for k in ("numFundingRounds", "numInvestors", "totalFunding", "operatingStatus",
                                               "ipoStatus", "monthlyVisitsGrowth", "growthScore", "heatScore",
                                               "founders", "keyPeople", "contacts")}
            payload["investors"] = (row.get("investors") or [])[:10]
            payload["fundingRounds"] = (row.get("fundingRounds") or [])[:5]
            payload["techStack"] = (row.get("techStack") or [])[:15]
            store.merge_enrichment(company["id"], "crunchbase", payload)
            fresh = store.get_company(company["id"]) or company
            if row.get("contactEmail") and _on_domain(row["contactEmail"], fresh["domain"]):
                store.add_email(company["id"], row["contactEmail"], kind="company", source="crunchbase")
            matched["crunchbase"] += 1

    for company in companies:  # mark attempted, so "not enriched" and "enriched, nothing found" differ
        store.merge_enrichment(company["id"], "status", {"attempted": True})
    return {"requested": len(companies), "matched": matched, "mismatches_dropped": mismatches, "runs": runs}


# -- 3. contacts ---------------------------------------------------------------------
def find_contacts(store: Store, runner: Runner, icp: dict[str, Any], company_ids: list[int], *,
                  per_company: int = 3, use_search: bool = True, max_titles: int = 2) -> dict[str, Any]:
    targets, runs, added, rejected = icp["target_titles"], [], 0, 0
    for cid in company_ids:
        company = store.get_company(cid)
        if not company:
            continue
        cb = company["enrichment"].get("crunchbase") or {}
        for person in [*(cb.get("contacts") or []), *(cb.get("keyPeople") or [])]:
            if len(store.contacts(cid)) >= per_company:
                break
            if isinstance(person, dict) and title_matches(person.get("title"), targets):
                handle = person.get("linkedinId")
                added += bool(store.add_contact(
                    cid, person.get("name") or "", title=person.get("title"),
                    department=", ".join(person.get("departments") or []) or None,
                    linkedin_url=f"https://www.linkedin.com/in/{handle}" if handle else None, source="crunchbase"))
        if not use_search:
            continue
        for title in targets[:max_titles]:
            need = per_company - len(store.contacts(cid))
            if need <= 0:
                break
            result = runner.run("linkedin_people", {"company": company["name"], "jobTitle": title,
                                                    "maxResults": need, "enrichProfiles": True})
            runs.append(_run_meta(result))
            if not result.items:
                break  # nothing indexed for this employer; more title variants would only burn run time
            for row in result.items:
                if _is_error(row) or not row.get("fullName"):
                    continue
                employer_ok = normalize_name(row.get("currentCompany")) == company["norm_name"] or (
                    company["linkedin_url"] and str(row.get("currentCompanyUrl") or "").rstrip("/").lower()
                    == company["linkedin_url"].rstrip("/").lower())
                if not employer_ok:  # fail closed: a past employee or a namesake is not a lead
                    rejected += 1
                    continue
                added += bool(store.add_contact(cid, row["fullName"], title=row.get("headline") or title,
                                                linkedin_url=row.get("profileUrl"),
                                                location=row.get("locationLocality"), source="linkedin_people"))
    return {"contacts_added": added, "rejected_wrong_employer": rejected, "runs": runs}


# -- 4. emails -----------------------------------------------------------------------
def _leads_in(row: dict[str, Any]) -> list[dict[str, Any]]:
    for key in LEAD_LIST_KEYS:
        if isinstance(row.get(key), list):
            return [p for p in row[key] if isinstance(p, dict)]
    return [row] if row.get("email") and (row.get("fullName") or row.get("firstName")) else []


def find_emails(store: Store, runner: Runner, icp: dict[str, Any], company_ids: list[int], *,
                leads_per_domain: int = 3, verify: bool = True, pages_per_domain: int = 10) -> dict[str, Any]:
    companies = {c["domain"]: c for c in (store.get_company(i) for i in company_ids) if c and c["domain"]}
    skipped = [i for i in company_ids if i not in {c["id"] for c in companies.values()}]
    if not companies:
        return {"person_emails": 0, "company_emails": 0, "skipped_no_website": skipped, "runs": []}
    websites = [c["website"] or f"https://{d}" for d, c in companies.items()]
    result = runner.run("contact_info", actors.contact_info_input(
        websites, icp["target_departments"], leads_per_domain, verify, pages_per_domain))
    person, inbox, off_domain = 0, 0, 0
    for row in result.items:
        domain = next((d for d in (normalize_domain(row.get(k)) for k in (
            "domain", "originalStartUrl", "companyWebsite", "url")) if d in companies), None)
        if not domain:
            continue
        cid = companies[domain]["id"]
        for address in row.get("emails") or []:
            if _on_domain(address, domain):
                inbox += store.add_email(cid, address, kind="company", source="contact_info")
            else:
                off_domain += 1  # vendor, tracker or agency address scraped off the page
        for lead in _leads_in(row):
            name = lead.get("fullName") or " ".join(filter(None, [lead.get("firstName"), lead.get("lastName")]))
            contact_id = store.add_contact(cid, name, title=lead.get("jobTitle"), department=lead.get("department"),
                                           seniority=lead.get("seniority"), linkedin_url=lead.get("linkedinProfile"),
                                           source="contact_info")
            if contact_id and lead.get("email"):
                verdict = (lead.get("emailVerification") or {}).get("result")
                person += store.add_email(cid, lead["email"], kind="person", contact_id=contact_id,
                                          verification=verdict, source="contact_info")
    return {"person_emails": person, "company_emails": inbox, "off_domain_dropped": off_domain,
            "skipped_no_website": skipped, "runs": [_run_meta(result)]}


def top_ids(store: Store, limit: int, need_domain: bool = False) -> list[int]:
    """Best-scored accounts first; optionally only those with a known website (email lookup needs one)."""
    ids = store.ranked_company_ids()
    if need_domain:
        ids = [i for i in ids if (store.get_company(i) or {}).get("domain")]
    return ids[:limit]


# -- 5. score + views ------------------------------------------------------------------
def score_all(store: Store, icp: dict[str, Any]) -> int:
    companies = store.list_companies()
    for company in companies:
        total, parts, reasons = score_company(company, store.signals(company["id"]), store.contacts(company["id"]),
                                              store.emails(company["id"]), icp)
        store.save_score(company["id"], total, parts, reasons)
    return len(companies)


def lead_summary(store: Store, company_id: int) -> dict[str, Any]:
    company = store.get_company(company_id) or {}
    score = store.get_score(company_id) or {}
    emails = store.emails(company_id)
    return {
        "id": company_id, "company": company.get("name"), "domain": company.get("domain"),
        "score": score.get("total"), "industry": company.get("industry"), "size": company.get("size_band"),
        "open_roles": len(store.signals(company_id, "hiring")), "contacts": len(store.contacts(company_id)),
        "emails": len(emails), "verified_emails": sum(e["verification"] == "ok" for e in emails),
        "enriched": bool(company.get("enriched_at")),
    }


def lead_detail(store: Store, company_id: int) -> dict[str, Any] | None:
    company = store.get_company(company_id)
    if not company:
        return None
    return {"company": company, "score": store.get_score(company_id), "signals": store.signals(company_id),
            "contacts": store.contacts(company_id), "emails": store.emails(company_id)}
