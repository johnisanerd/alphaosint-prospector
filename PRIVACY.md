# Privacy policy: Alpha OSINT Prospector

Last updated: 2026-11-02

Alpha OSINT Prospector ("the plugin") is open-source software published by Alpha OSINT (alphaosint.com). It runs on your computer as a Claude Code plugin. This policy explains what data it handles and where that data goes.

## What Alpha OSINT collects

Nothing. The plugin has no Alpha OSINT server, account system, analytics or telemetry. Alpha OSINT does not receive your prompts, your Ideal Customer Profile, your leads or your Apify token.

## Data the plugin sends to Apify

To find and enrich companies, the plugin calls the Apify API (`api.apify.com`) with the Apify token you provide, and runs the Apify Actors listed in the README. A request can contain:

- your ICP's hiring keywords, locations and target job titles;
- company names, website domains and LinkedIn or Crunchbase company pages;
- the company websites it checks for business contacts.

Apify processes these runs under its own terms and privacy policy (https://apify.com/privacy-policy), and bills them to your Apify account. Most of the Actors are published by the author of this plugin, and one (the contact details Actor) is published by a third party. Apify does not give Actor publishers access to your runs' inputs or results.

## Data stored on your computer

The plugin keeps a SQLite database, `prospector.db`, in the plugin's data directory (`~/.claude/plugins/data/...`). It holds:

- your saved ICP;
- the companies it found, with firmographic, hiring and funding data;
- named business contacts (name, job title, LinkedIn URL, work email and verification status);
- scores with their reasons, and a log of Actor runs and their cost.

Your Apify token is stored by Claude Code in your system's credential store, not in this database. The data stays until you delete it or uninstall the plugin, at which point Claude Code removes the data directory. Exports are written only to the file path you choose.

## Personal data and your responsibilities

Named contacts and work emails are personal data under the GDPR and similar laws. You are the controller of any personal data you collect with the plugin, and you need a lawful basis to hold and use it. The plugin only researches: it does not send email, connect on LinkedIn, or contact anyone.

## Changes and contact

Changes to this policy are made in this file, and its history is public in the repository. Questions: open an issue at https://github.com/johnisanerd/alphaosint-prospector/issues.
