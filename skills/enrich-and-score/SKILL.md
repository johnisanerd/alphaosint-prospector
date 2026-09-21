---
name: enrich-and-score
description: "Add Indeed employer data, LinkedIn company data and Crunchbase funding data to sourced accounts and re-score them 0-100 against the ICP, using Alpha OSINT Prospector. Use when the user says enrich these companies, which of these are funded, score my leads, rank the list, or why did this company score low. Explains every score from stored reasons and never from general knowledge."
---

# Enrich and score

Shared rules: `../prospect/references/conventions.md`.

## Steps
1. `list_leads(limit=25)` to see what is unenriched (`enriched: false`).
2. `enrich_companies(top=10)` for the best unenriched accounts, or pass `company_ids` for specific ones. Worst case is about 2.6 cents per company for all three sources.
3. Report `matched` per source and `mismatches_dropped`.
4. `list_leads` again. Scores are recomputed automatically after each stage; `score_leads` is only needed after the ICP changes.

## How matching works, so you can explain it
- The company website domain is the join key. The Indeed employer page runs first because it is the cheapest place to learn the website; it is accepted only on an exact normalized name match. LinkedIn lookups go by name and are accepted only when the returned website matches the account's domain, or when no domain is known on one side and the names match exactly.
- Crunchbase lookups go by domain when one is known, which is far more reliable than by name.
- A dropped match stays dropped. Tell the user they can confirm the right LinkedIn URL and you will re-run with it. Do not pick one yourself.

## How the score works
fit (industry, headcount, country) + hiring (count and recency of matching roles) + funding (recency of last round) + momentum (traffic growth, urgent hiring) + reachability (named contact, email, verified email), weighted by the ICP. Each part lists its reasons in `get_lead`.

Known limits to state plainly when they matter:
- Round dates come from the LinkedIn funding summary. Crunchbase publicly shows round structure and investors but not dates or amounts, so "2 round(s) on record, date not public" is the honest output.
- "headcount unknown" means no source returned a size band. It is not a small company.
