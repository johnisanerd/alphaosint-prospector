---
name: find-decision-makers
description: "Find named decision-makers and verified work emails at the top-scored accounts, using Alpha OSINT Prospector. Pulls contacts already present in enrichment data for free, looks up business leads and verifies emails through the website contact Actor, and searches LinkedIn for the ICP's target titles. Use when the user says who do I contact, find the VP of Sales at these companies, get me emails, or find contacts for my top leads."
---

# Find decision-makers and emails

Shared rules: `../prospect/references/conventions.md`. Named people are personal data. Only run this for accounts the user intends to contact.

## Steps
1. `list_leads(limit=10)`. Pick accounts scoring 40 or more unless the user names others.
2. `find_emails(top=5, leads_per_domain=3, verify=true)`.
   - Needs a known website. Accounts without one come back in `skipped_no_website`; run enrich-and-score on them first.
   - Needs $0.50 of session budget left even though real cost is about 5 cents per company. If `budget_exceeded` mentions "at least $0.50", that is why.
   - The crawl is capped at 15 pages and depth 1 per site by the server. Do not ask for more; contact pages are near the home page and this Actor bills per page.
   - On the Apify free plan the lead and verification add-ons cost $0.10 each instead of half a cent. If `get_config` or the user says free plan, set `leads_per_domain=0` and only collect the company inbox.
3. `find_contacts(top=5)`. Free contacts from enrichment first, then LinkedIn search for the first two target titles. People whose current employer does not match are rejected; report `rejected_wrong_employer` as a number, not names.
4. The email Actor filters by department, not by title, so it also returns neighbours of the buyer (account managers, enablement). Present people whose title matches the ICP's target titles first and label the rest as "same department, not a target title". The export marks this in `title_match`.
5. For each account, `get_lead` and present: name, title, LinkedIn URL, email, verification.

## Reading verification
- `ok`: verified deliverable.
- `catch_all`: the domain accepts everything, so the address cannot be confirmed. Not charged. Label as unverified.
- `unknown` or empty: not confirmed. Label as unverified.
- `invalid` or `disposable`: do not show as a usable email.

Addresses found on the site that belong to another domain (form vendors, trackers, agencies) are dropped and counted in `off_domain_dropped`.

## Boundaries
No personal email addresses, no phone lookups, no guessing an address from a name pattern. If nothing verified was found, say so and give the company inbox.
