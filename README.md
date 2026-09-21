# Alpha OSINT Prospector

B2B prospecting inside Claude. Describe your ideal customer once, and get back a ranked list of companies that are hiring for the roles you sell into, with funding data, a 0-100 score you can audit, named decision-makers and verified work emails.

It is a Claude Code plugin: an MCP server with 14 tools, a local SQLite lead store, and 6 skills. It researches. It never sends anything.

Built by [Alpha OSINT](https://alphaosint.com) on our own [Apify Actors](https://apify.com/johnvc?fpr=9n7kx3&fp_sid=skillrepo).

## Why another prospecting tool

Most Claude prospecting tools read LinkedIn, one URL at a time, and ask the model to say "High / Medium / Low". That leaves gaps this project fills:

| Gap | What Prospector does |
|---|---|
| No way to find accounts | Sources companies from live job postings: a company hiring three SDRs this week is a buying signal |
| LinkedIn is the only source | Joins Indeed, LinkedIn and Crunchbase on the company's website domain, and drops namesakes instead of guessing |
| Scores are prose | A deterministic 0-100 score. Same data, same score, with a stored reason for every point |
| Spend limits are a polite request in a prompt | Hard per-call and per-session caps in code, plus a platform-side charge cap on every run |
| Emails are an afterthought | Named leads by department with a verification verdict, stored and exported |

## The pipeline

```
ICP  ->  source (job postings)  ->  enrich (firmographics + funding)  ->  emails + decision-makers  ->  score  ->  leads.csv
```

| Stage | Actor | What it adds |
|---|---|---|
| Source | [Indeed Jobs API](https://apify.com/johnvc/indeed-jobs-api?fpr=9n7kx3&fp_sid=skillrepo) | Open roles by keyword, filtered to titles that really match |
| Source (optional) | [LinkedIn Jobs API](https://apify.com/johnvc/linkedin-jobs-api?fpr=9n7kx3&fp_sid=skillrepo) | A second hiring feed |
| Enrich | [Indeed Company API](https://apify.com/johnvc/indeed-company-api?fpr=9n7kx3&fp_sid=skillrepo) | Website (the join key), industry, headcount, HQ, employer rating |
| Enrich | [LinkedIn Company API](https://apify.com/johnvc/linkedin-company-api?fpr=9n7kx3&fp_sid=skillrepo) | Headcount band, industry, HQ, followers, last funding round |
| Enrich | [Crunchbase Company API](https://apify.com/johnvc/crunchbase-company-api?fpr=9n7kx3&fp_sid=skillrepo) | Rounds, investors, key people, traffic growth, tech stack |
| People | [LinkedIn People Search API](https://apify.com/johnvc/linkedin-people-search-api?fpr=9n7kx3&fp_sid=skillrepo) | People holding your target titles at the account |
| Emails | [Contact Details Scraper](https://apify.com/vdrmota/contact-info-scraper?fpr=9n7kx3&fp_sid=skillrepo) (third party) | Company inbox, named leads by department, email verification |

Related Actors you can chain by hand: [LinkedIn Profile API](https://apify.com/johnvc/linkedin-profile-api?fpr=9n7kx3&fp_sid=skillrepo), [LinkedIn Posts API](https://apify.com/johnvc/linkedin-posts-api?fpr=9n7kx3&fp_sid=skillrepo), [PitchBook Company API](https://apify.com/johnvc/pitchbook-company-api?fpr=9n7kx3&fp_sid=skillrepo), [Google Maps Place ID Contact API](https://apify.com/johnvc/google-maps-place-id-contact-api?fpr=9n7kx3&fp_sid=skillrepo).

## Install

You need [uv](https://docs.astral.sh/uv/), an [Apify account](https://apify.com?fpr=9n7kx3&fp_sid=skillrepo) (a paid plan is recommended, see Cost) and Claude Code. New to Claude Code? [Try it with this referral link](https://claude.ai/referral/uIlpa7nPLg).

In Claude Code:

```
/plugin marketplace add johnisanerd/alphaosint-prospector
```

```
/plugin install alphaosint-prospector@alphaosint
```

Then add your Apify token and restart Claude Code:

```bash
mkdir -p ~/.alphaosint && echo "APIFY_TOKEN=your_token_here" >> ~/.alphaosint/.env
```

MCP server only (Claude Desktop, Cursor, anything that speaks MCP):

```json
{
  "mcpServers": {
    "alphaosint-prospector": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/johnisanerd/alphaosint-prospector", "alpha-prospector", "serve"]
    }
  }
}
```

## Use it

Say what you want:

- "Set up my ICP. We sell sales engagement software to US SaaS companies with 50 to 1000 people."
- "Find me 25 leads."
- "Why did the third one score low?"
- "Get me the VP of Sales and an email for the top five."
- "Export the list."

Or run the whole thing without Claude:

```bash
uvx --from git+https://github.com/johnisanerd/alphaosint-prospector alpha-prospector run --icp examples/icp.example.json --max-companies 10 --budget 2
```

### Skills

| Skill | Does |
|---|---|
| `prospect` | The full pipeline, ICP to CSV |
| `define-icp` | Interviews you and saves the ICP |
| `source-accounts` | New companies from hiring signals |
| `enrich-and-score` | Firmographics, funding, and the score explained |
| `find-decision-makers` | Named contacts and verified emails |
| `export-leads` | CSV, JSON or XLSX, plus spend |

### MCP tools

`get_config`, `get_icp`, `set_icp`, `estimate_cost`, `source_companies`, `enrich_companies`, `find_contacts`, `find_emails`, `score_leads`, `list_leads`, `get_lead`, `export_leads`, `list_runs`, `get_spend`.

## The ICP

One JSON object drives sourcing, filtering and scoring. See [examples/icp.example.json](examples/icp.example.json).

| Field | Meaning |
|---|---|
| `hiring_keywords` | Job titles that signal a need for what you sell. One paid search each, so keep it to 1 to 3 |
| `industries` | Lowercase fragments matched against the employer's industry text |
| `employee_range` | `[min, max]`, `[0, 0]` for any |
| `countries` | Two-letter codes; the first one is the job board searched |
| `target_titles` | Decision-maker titles, matched word by word ("VP Sales" matches "VP of Sales") |
| `target_departments` | Departments for the email lead lookup, for example `c_suite`, `sales` |
| `exclude_industries` | Defaults to staffing and recruiting, because agencies post the same titles |
| `weights` | Points per score part. Defaults: fit 35, hiring 30, funding 15, momentum 10, reachability 10 |

## The score

| Part | Full marks when |
|---|---|
| Fit | Industry, headcount and country all match the ICP |
| Hiring | Five or more matching open roles, newest inside your recency window |
| Funding | Last round within six months |
| Momentum | Web traffic growing, and urgent or multi-seat hiring |
| Reachability | A named decision-maker with a verified email |

Unknown data scores zero and the reason says "unknown". An account nobody has enriched cannot outrank one that was checked.

## Cost

You pay Apify for the Actor runs, per result. The server estimates each call at list price before it runs, refuses calls over your caps, and starts every run with a platform-side maximum charge.

| Stage | Worst case at list price |
|---|---|
| Source | about $0.004 to $0.0095 per job row |
| Enrich | about $0.026 per company (Indeed, LinkedIn and Crunchbase) |
| People search | about $0.0016 per person returned |
| Emails | about $0.05 per company (10 pages, 3 leads, 3 verifications) |

Defaults: $2.00 per session, $1.00 per call. Change them in `~/.alphaosint/.env` (see [.env.example](.env.example)).

Two things to know:

- The email Actor refuses runs whose charge cap is under $0.50, so that stage needs $0.50 of session budget left even when the real cost is a few cents.
- On Apify's free plan that Actor prices its lead and verification add-ons at $0.10 each instead of about half a cent. Use a paid plan, or set `leads_per_domain=0`.

## Limits

- Crunchbase shows round structure and investors publicly, not dates or amounts. Round dates come from the LinkedIn funding summary when LinkedIn has one.
- Job boards match titles loosely. Postings whose title does not contain every word of one of your hiring keywords are ignored and counted, so add each real variant as its own keyword.
- LinkedIn job rows carry no website, so those accounts need enrichment before emails can be found.
- People search depends on public search indexing of LinkedIn profiles. Small companies often return nobody. The email step usually finds named people where search does not.
- A `catch_all` or `unknown` email verdict means unverified. The export says so.

## Privacy and terms

Data is stored locally in `~/.alphaosint/prospector.db`. Named contacts and work emails are personal data under GDPR and similar laws; you need a lawful reason to hold and use them. The Actors read public pages. You are responsible for complying with the terms of the sites involved and with anti-spam law where you operate. This project sends no messages.

## Development

```bash
git clone https://github.com/johnisanerd/alphaosint-prospector && cd alphaosint-prospector
```

```bash
uv venv && uv pip install -e ".[dev,xlsx]" && uv run pytest -q
```

Tests use a fake Apify backend and spend nothing.

## Credits

Inspired by [insaight](https://github.com/spirosbax/insaight) by Spiros Baxevanakis, which showed how well an MCP server plus skills works for prospect research. Prospector is an independent implementation with a different scope: account sourcing, multi-source enrichment and scoring.

Disclosure: apify.com links carry the author's affiliate code, and the `johnvc/*` Actors are built by the author.

MIT License.
