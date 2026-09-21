"""Entity resolution. The registrable domain is the join key across sources.

Rules (fail closed):
- Two records with domains are the same company only when the domains match.
- If only one side has a domain, the normalized names must match exactly.
- Anything else is a mismatch and the enrichment row is dropped, never guessed.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Hosts that show up in "website" fields but are never a company's own site.
NON_COMPANY_HOSTS = {
    "linkedin.com", "indeed.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "crunchbase.com", "glassdoor.com", "linktr.ee", "bit.ly", "google.com",
    "wellfound.com", "github.com", "medium.com", "tiktok.com",
}

_TWO_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
    "co.kr", "co.in", "com.br", "com.mx", "com.sg", "com.hk", "co.za", "com.tr", "com.ar",
}

_LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|ag|sa|sas|"
    r"bv|plc|pty|pte|holdings|group)\b\.?",
    re.IGNORECASE,
)


def normalize_domain(url: str | None) -> str | None:
    """Return the registrable domain ("https://www.Acme.co.uk/x" -> "acme.co.uk") or None."""
    if not url or not isinstance(url, str):
        return None
    raw = url.strip().lower()
    if not raw:
        return None
    if "//" not in raw:
        raw = "//" + raw
    host = (urlparse(raw).hostname or "").strip(".")
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES:
        domain = ".".join(labels[-3:])
    else:
        domain = ".".join(labels[-2:])
    if domain in NON_COMPANY_HOSTS:
        return None
    return domain


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = name.lower().replace("&", " and ")
    text = _LEGAL_SUFFIXES.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def same_company(
    account_name: str | None,
    account_domain: str | None,
    row_name: str | None,
    row_website: str | None,
) -> tuple[bool, str]:
    """Decide whether an enrichment row belongs to the account. Returns (ok, reason)."""
    row_domain = normalize_domain(row_website)
    if account_domain and row_domain:
        if account_domain == row_domain:
            return True, "domain match"
        return False, f"domain mismatch ({row_domain} vs {account_domain})"
    left, right = normalize_name(account_name), normalize_name(row_name)
    if left and left == right:
        return True, "exact name match"
    return False, "no domain on one side and names differ"


def person_key(full_name: str | None) -> str:
    return re.sub(r"[^a-z]+", " ", (full_name or "").lower()).strip()
