"""Read one Linear issue by identifier (ENG-123) through Linear's GraphQL API."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_URL = "https://api.linear.app/graphql"
QUERY = """
query Issue($id: String!) {
  issue(id: $id) {
    identifier
    title
    description
    url
    state { name }
    labels { nodes { name } }
  }
}
"""


def fetch_linear(key: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    token = os.environ.get("LINEAR_API_KEY")
    if not token:
        raise RuntimeError("LINEAR_API_KEY is not set")
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        resp = client.post(API_URL, json={"query": QUERY, "variables": {"id": key}},
                           headers={"Authorization": token, "Content-Type": "application/json"})
    finally:
        if own:
            client.close()
    if resp.status_code != 200:
        raise RuntimeError(f"Linear API returned {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Linear API error for {key}: {body['errors'][0].get('message')}")
    issue = (body.get("data") or {}).get("issue")
    if not issue:
        raise RuntimeError(f"Linear issue {key} not found")
    labels = [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])]
    ticket_type = "bug" if any(label.lower() in ("bug", "defect") for label in labels) else None
    return {
        "markdown": issue.get("description") or "",
        "title": issue.get("title") or "",
        "type": ticket_type,
        "source": {"tracker": "linear", "id": issue.get("identifier", key), "url": issue.get("url"),
                   "state": (issue.get("state") or {}).get("name"), "labels": labels},
    }


__all__ = ["fetch_linear"]
