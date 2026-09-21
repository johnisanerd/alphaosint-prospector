---
name: source-accounts
description: "Find new target companies for the saved ICP from live job postings, using Alpha OSINT Prospector. Searches Indeed (and optionally LinkedIn Jobs) for the ICP's hiring keywords, groups postings by employer, drops agencies and exclusions, keeps the best fits, and records each posting as a dated hiring signal. Use when the user says find more companies, who is hiring for X, refresh my pipeline, or add accounts. Not for researching one named company; use enrich-and-score with that company instead."
---

# Source accounts from hiring signals

Shared rules: `../prospect/references/conventions.md`.

## Steps
1. `get_icp`. None saved: run define-icp.
2. `estimate_cost(max_companies=N, max_jobs_per_keyword=M)`. Sourcing cost is driven by M times the number of hiring keywords (each job row with company details lists at about one cent). State the figure.
3. `source_companies(sources=["indeed_jobs"], max_companies=N, max_jobs_per_keyword=M)`. Rule of thumb: M is about 4 times N. Job boards match loosely, and postings whose title does not contain every word of a hiring keyword are ignored (`off_title_jobs_ignored`).
4. Add `"linkedin_jobs"` to `sources` only when the user asks or Indeed came back thin. LinkedIn job rows carry no company website, so those accounts cannot get emails until enrich-and-score finds a domain.
5. `list_leads(limit=N)` and summarize: how many companies, how many open roles, what was dropped and why.

## Reading the result
- `dropped` names each excluded company with the reason. Agencies are caught by industry or by name ("staffing", "recruiting").
- Running it again is safe. Postings are deduplicated by job id, so `new_hiring_signals: 0` means nothing new was posted, not that the run failed.
- A high `off_title_jobs_ignored` with few companies means the keyword is phrased differently in real postings. Suggest the variant ("business development representative" next to "sales development representative") and let the user decide; each keyword is a separate paid search.
- Sourced accounts usually carry no industry, size or website yet, so scores at this stage mostly reflect hiring. Tell the user that funding and reachability are still empty until the next stages run.
