---
name: export-leads
description: "Export the ranked Alpha OSINT Prospector lead list to CSV, JSON or XLSX, and report spend. One row per contact with company score, score reasons, hiring and funding signals, email and verification status. Use when the user says export my leads, give me the CSV, download the list, or how much have I spent."
---

# Export leads

Shared rules: `../prospect/references/conventions.md`.

1. `export_leads(path="~/alphaosint-leads.csv", format="csv", min_score=0)`. Use `min_score=40` when the user wants only qualified accounts. `xlsx` needs the optional `openpyxl` extra; on error, fall back to csv and say so.
2. Report the path, row count and company count.
3. `get_spend` and `list_runs(limit=10)` when the user asks about cost. Each run has an Apify run id they can open in the Apify Console.

Columns: rank, score, company, domain, website, industry, size, hq, country, open_roles, newest_role, role_titles, funding, investors, contact_name, contact_title, title_match, contact_linkedin, email, email_type, email_verification, five score parts, why, linkedin_url, crunchbase_url, sources.

`email_type` is `person` for a named contact's address and `company` for a shared inbox. When a contact has no address of their own, the row carries the company inbox and says `company`.
