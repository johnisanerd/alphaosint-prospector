---
name: prospect
description: "Run the full Alpha OSINT Prospector pipeline from an Ideal Customer Profile to a ranked leads file. Finds companies hiring for roles that signal a need, enriches them with LinkedIn and Crunchbase data, scores each 0-100 with reasons, finds decision-makers and verified work emails, and exports CSV. Use when the user says find me leads, build a prospect list, who should I sell to, find companies hiring SDRs (or any role), or prospect for my ICP. For one stage only use define-icp, source-accounts, enrich-and-score, find-decision-makers or export-leads."
---

# Prospect: ICP in, ranked leads out

Most lead lists start from a static database. This one starts from a live buying signal: a company that posted a job this week for the role your product serves. The pipeline then checks whether that company fits, whether it has money, and who to talk to.

Read `references/conventions.md` first. The spend and fail-closed rules there apply to every step.

## Step 1. ICP
Call `get_icp`. If nothing is saved, run the define-icp skill. Do not invent an ICP from the user's company name.

## Step 2. Estimate, then source
Call `estimate_cost` with the limits below and state the worst case. Then:

```
source_companies(max_companies=25, max_jobs_per_keyword=40)
```

Job boards match loosely: a search for "sales development representative" also returns "Inside Sales Representative - Flooring". The server ignores postings whose title does not contain every word of one of the ICP's hiring keywords and reports them as `off_title_jobs_ignored`. Expect to keep a third or less, so ask for about 4 jobs per company you want. If almost everything was ignored, the keyword is phrased differently on job boards; go back to define-icp and add the variant as its own keyword. Read the `dropped` list (agencies, exclusions) to the user in one line.

Sourced accounts usually have no industry, size or website yet. Scores mean little until Step 3.

## Step 3. Enrich the top accounts
```
enrich_companies(top=10)
```
This runs three lookups in order: the Indeed employer page (cheap, and usually supplies the website that the other two are joined on), LinkedIn, then Crunchbase by domain. Report `matched` and `mismatches_dropped`. A mismatch is a namesake with a different website. It is expected for common names and is not an error.

## Step 4. People and emails
Emails first, because the email step also returns named people for the ICP's departments:
```
find_emails(top=5, leads_per_domain=3, verify=true)
find_contacts(top=5)
```
`find_contacts` takes names from the enrichment data for free, then searches LinkedIn for the ICP's titles. Companies with no website are skipped by `find_emails` and listed in `skipped_no_website`.

## Step 5. Show and export
`list_leads(limit=10)`, then for the top 3 call `get_lead` and give, per account: score, the two strongest reasons, open roles, best contact, email and its verification status. Then `export_leads()` and give the file path and `get_spend`.

## Judgment calls
- Score under 40 after enrichment: say it is a weak fit and why. Do not pad the list.
- No funding data does not mean no money. Bootstrapped and public companies score zero on funding. Say "no round on record".
- The user asks you to email the leads: refuse that part. This tool researches and sends nothing.
