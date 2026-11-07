"""Read one Jira Cloud issue by key (PROJ-123) through the REST API v3.

The description comes back as ADF and is converted to Markdown. If your
acceptance criteria live in a custom field, set JIRA_AC_FIELD and it's
appended as an `## Acceptance criteria` section.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ticket_quality.trackers.adf import adf_to_markdown


def fetch_jira(key: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email, token = os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")
    if not (base and email and token):
        raise RuntimeError("set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN")
    ac_field = os.environ.get("JIRA_AC_FIELD", "").strip()
    fields = ["summary", "description", "issuetype", "labels", "status"] + ([ac_field] if ac_field else [])
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        resp = client.get(f"{base}/rest/api/3/issue/{key}", params={"fields": ",".join(fields)},
                          auth=(email, token), headers={"Accept": "application/json"})
    finally:
        if own:
            client.close()
    if resp.status_code == 404:
        raise RuntimeError(f"Jira issue {key} not found (or no permission to see it)")
    if resp.status_code != 200:
        raise RuntimeError(f"Jira API returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    f = data.get("fields") or {}
    markdown = adf_to_markdown(f.get("description"))
    if ac_field and f.get(ac_field):
        ac = adf_to_markdown(f[ac_field]).strip()
        markdown = _insert_before_agent_context(markdown, f"## Acceptance criteria\n\n{ac}\n")
    return {
        "markdown": markdown,
        "title": f.get("summary") or "",
        "type": ((f.get("issuetype") or {}).get("name") or None),
        "source": {"tracker": "jira", "id": data.get("key", key), "url": f"{base}/browse/{data.get('key', key)}",
                   "state": (f.get("status") or {}).get("name"), "labels": f.get("labels") or []},
    }


def _insert_before_agent_context(markdown: str, section: str) -> str:
    """Keep the agent context last when appending a section from another field."""
    lower = markdown.lower()
    for marker in ("<details", "## agent context", "# agent context"):
        i = lower.find(marker)
        if i != -1 and (marker != "<details" or "agent" in lower[i:i + 200]):
            return markdown[:i] + section + "\n" + markdown[i:]
    return markdown.rstrip() + "\n\n" + section


__all__ = ["fetch_jira"]
