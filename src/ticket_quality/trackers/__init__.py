"""Fetch tickets from Linear and Jira, and work out which tracker an id belongs to.

Environment:
  Linear: LINEAR_API_KEY (a personal API key, Settings > Security & access)
  Jira:   JIRA_BASE_URL (https://yourcompany.atlassian.net), JIRA_EMAIL, JIRA_API_TOKEN,
          and optionally JIRA_AC_FIELD (e.g. customfield_10035) if acceptance
          criteria live in their own field.
  TICKET_LINT_TRACKER=linear|jira picks one when an id like ENG-123 could be either.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ticket_quality.trackers.jira import fetch_jira
from ticket_quality.trackers.linear import fetch_linear

ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
LINEAR_URL = re.compile(r"linear\.app/[^/]+/issue/([A-Za-z][A-Za-z0-9_]*-\d+)")
JIRA_BROWSE = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]*-\d+)")


@dataclass
class FetchedTicket:
    markdown: str
    title: str
    type: str | None
    source: dict


class TrackerError(RuntimeError):
    pass


def configured() -> list[str]:
    out = []
    if os.environ.get("LINEAR_API_KEY"):
        out.append("linear")
    if all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")):
        out.append("jira")
    return out


def resolve(ref: str, tracker: str | None = None) -> tuple[str, str] | None:
    """(tracker, key) for a tracker reference, or None if `ref` isn't one."""
    if m := LINEAR_URL.search(ref):
        return "linear", m.group(1).upper()
    if "atlassian.net" in ref or "/browse/" in ref or "selectedIssue=" in ref:
        m = JIRA_BROWSE.search(ref) or re.search(r"selectedIssue=([A-Za-z][A-Za-z0-9_]*-\d+)", ref)
        if m:
            return "jira", m.group(1).upper()
    if not ISSUE_KEY.match(ref):
        return None
    key = ref.upper()
    chosen = tracker or os.environ.get("TICKET_LINT_TRACKER")
    if chosen:
        return chosen.lower(), key
    available = configured()
    if len(available) == 1:
        return available[0], key
    if not available:
        raise TrackerError(f"{ref} looks like an issue key, but no tracker is configured: set "
                           "LINEAR_API_KEY, or JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN")
    raise TrackerError(f"{ref} could be Linear or Jira: pass --tracker linear|jira "
                       "(or set TICKET_LINT_TRACKER)")


def fetch(tracker: str, key: str) -> FetchedTicket:
    if tracker == "linear":
        return FetchedTicket(**fetch_linear(key))
    if tracker == "jira":
        return FetchedTicket(**fetch_jira(key))
    raise TrackerError(f"unknown tracker {tracker!r} (linear or jira)")


__all__ = ["FetchedTicket", "TrackerError", "configured", "fetch", "resolve"]
