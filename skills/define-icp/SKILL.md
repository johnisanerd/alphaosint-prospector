---
name: define-icp
description: "Interview the user and save an Ideal Customer Profile for Alpha OSINT Prospector. The ICP sets which job postings count as a buying signal, which companies fit, which titles to find, and the weights of the 0-100 lead score. Use when the user says set up my ICP, define my ideal customer, change who we target, or when another prospector skill reports that no ICP is saved."
---

# Define the ICP

Everything downstream is scored against this file, so ten minutes here saves money later. Shared rules: `../prospect/references/conventions.md`.

## Step 1. Look before asking
Call `get_icp`. If one is saved, show it in plain words and ask what to change. Do not start over.

## Step 2. Ask only what you need
Ask in one message, short:
1. What do you sell, in one line?
2. Which job posting means a company needs it now? (the hiring signal; give 1 to 3 job titles)
3. Which industries and what headcount range?
4. Which country?
5. Who signs or champions the purchase? (2 to 4 titles)

## Step 3. Translate carefully
- `hiring_keywords`: job titles as they appear on job boards. Each keyword is a separate paid search, so keep it to 1 to 3. A posting counts only when its title contains every word of a keyword, so list real variants separately ("sales development representative", "business development representative"). Generic titles ("sales representative") pull in car dealers and franchises. Prefer a title that implies the ICP ("sales development representative", "revenue operations manager").
- `industries`: lowercase fragments matched against the company's industry text, for example "software", "information technology", "financial services". Use fragments, not full taxonomy names.
- `employee_range`: `[min, max]`; `[0, 0]` means any.
- `target_titles`: matched word by word, so "VP Sales" also matches "VP of Sales". Add the spelled-out form too ("Vice President Sales").
- `target_departments`: only these values are accepted: c_suite, sales, marketing, product, engineering_technical, finance, human_resources, information_technology, operations, legal, design, consulting, education, medical_health.
- `exclude_industries` defaults to staffing and recruiting, because agencies post the same titles for their clients. Keep it unless the user sells to agencies.
- `weights`: keep the defaults (fit 35, hiring 30, funding 15, momentum 10, reachability 10) unless the user has a reason. Selling to bootstrapped firms: move funding weight into fit.

## Step 4. Save and confirm
Call `set_icp`. If it returns an error, fix the named field and retry once. Read the saved ICP back in three lines and suggest the prospect skill next.
