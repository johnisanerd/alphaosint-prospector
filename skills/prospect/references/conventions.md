# Conventions shared by every Alpha OSINT Prospector skill

## Tools
All tools come from the `alphaosint-prospector` MCP server. If they are not loaded, search your tools for "alphaosint". Call `get_config` once per session. If `apify_token_set` is false, stop and give the setup line from the README. Do not try another route.

## Money
- Every paid tool is estimated and capped by the server. You cannot bypass the cap, so do not try to split one call into many to get under it.
- Before the first paid call in a session, call `estimate_cost` with the limits you plan to use and tell the user the worst-case figure. Go ahead without asking when it is under $0.50. Ask first when it is more.
- On `budget_exceeded`, report the message as written. The user raises the cap in `~/.alphaosint/.env`; you lower limits or stop.
- The email step needs at least $0.50 of session budget left, because the email Actor refuses runs with a smaller charge cap. Real cost stays near the estimate (about $0.05 per company).
- After the last paid call, report `get_spend`.

## Cheap reads first
`list_leads` returns one slim line per account. Use `get_lead` only for accounts you will talk about. Never dump `get_lead` output into chat; summarize it.

## Fail closed
- The server drops enrichment rows whose website domain differs from the account's, and people whose current employer differs. These show up as `mismatches_dropped` and `rejected_wrong_employer`. Report the counts. Never re-add a dropped match by hand.
- Unknown data scores zero and says so in the score reasons. Do not fill gaps from memory. If headcount is unknown, say unknown.
- An email marked `ok` was verified. `catch_all`, `unknown` or "not checked" means unverified, and you say so every time you show it.

## What this tool is not
It researches. It does not send email, connect on LinkedIn, or write outreach. It stores business contact data locally in `~/.alphaosint/prospector.db`; the user is responsible for having a lawful reason to hold it (GDPR and similar rules apply to named people).
