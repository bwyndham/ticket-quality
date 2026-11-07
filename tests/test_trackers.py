import json

import httpx
import pytest

from ticket_quality.trackers import TrackerError, resolve
from ticket_quality.trackers.adf import adf_to_markdown
from ticket_quality.trackers.jira import fetch_jira
from ticket_quality.trackers.linear import fetch_linear
from ticket_quality.ticket import parse_ticket


def text(s, *marks):
    node = {"type": "text", "text": s}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def para(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


ADF = {
    "type": "doc", "version": 1,
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Summary")]},
        para(text("Finance needs a CSV of "), text("filtered", "strong"), text(" orders.")),
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Acceptance criteria")]},
        {"type": "taskList", "content": [
            {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [text("Button downloads the CSV")]},
            {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [text("Columns: id, date, total")]},
        ]},
        {"type": "expand", "attrs": {"title": "Agent context"}, "content": [
            para(text("See "), text("api/orders.py", "code")),
            {"type": "codeBlock", "attrs": {"language": "sql"}, "content": [text("select 1")]},
        ]},
    ],
}


def test_adf_to_markdown_round_trips_through_the_parser():
    md = adf_to_markdown(ADF)
    assert "**filtered**" in md and "- [ ] Button downloads the CSV" in md and "- [x] Columns" in md
    t = parse_ticket(md, title="Export filtered orders as CSV")
    assert t.agent_context_style == "collapsed"
    assert "select 1" in t.agent_context and "select 1" not in t.human_markdown
    assert t.acceptance_criteria == ["Button downloads the CSV", "Columns: id, date, total"]


def test_linear_fetch(monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_x")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "lin_api_x"
        body = json.loads(request.content)
        assert body["variables"] == {"id": "ENG-12"}
        return httpx.Response(200, json={"data": {"issue": {
            "identifier": "ENG-12", "title": "Fix it", "description": "## Summary\nhi", "url": "https://linear.app/x/issue/ENG-12",
            "state": {"name": "Todo"}, "labels": {"nodes": [{"name": "Bug"}]}}}})

    got = fetch_linear("ENG-12", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert got["type"] == "bug" and got["source"]["id"] == "ENG-12" and got["markdown"].startswith("## Summary")


def test_linear_errors(monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "k")
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"errors": [{"message": "Entity not found"}]})))
    with pytest.raises(RuntimeError, match="Entity not found"):
        fetch_linear("ENG-1", client=client)


def test_jira_fetch_with_ac_field(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net/")
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "t")
    monkeypatch.setenv("JIRA_AC_FIELD", "customfield_1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/issue/PROJ-9"
        assert "customfield_1" in request.url.params["fields"]
        return httpx.Response(200, json={"key": "PROJ-9", "fields": {
            "summary": "Export orders", "issuetype": {"name": "Story"}, "labels": [], "status": {"name": "To Do"},
            "description": {"type": "doc", "content": [para(text("Why it matters.")),
                                                       {"type": "expand", "attrs": {"title": "Agent context"},
                                                        "content": [para(text("notes"))]}]},
            "customfield_1": {"type": "doc", "content": [{"type": "bulletList", "content": [
                {"type": "listItem", "content": [para(text("CSV downloads"))]}]}]},
        }})

    got = fetch_jira("PROJ-9", client=httpx.Client(transport=httpx.MockTransport(handler)))
    t = parse_ticket(got["markdown"], title=got["title"], ticket_type=got["type"])
    assert t.acceptance_criteria == ["CSV downloads"]
    assert t.agent_context_last and t.agent_context == "notes"
    assert got["source"]["url"] == "https://acme.atlassian.net/browse/PROJ-9"


def test_resolve(monkeypatch):
    for k in ("LINEAR_API_KEY", "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "TICKET_LINT_TRACKER"):
        monkeypatch.delenv(k, raising=False)
    assert resolve("notes.md") is None
    assert resolve("https://linear.app/acme/issue/ENG-5/some-title") == ("linear", "ENG-5")
    assert resolve("https://acme.atlassian.net/browse/PROJ-7") == ("jira", "PROJ-7")
    with pytest.raises(TrackerError, match="no tracker is configured"):
        resolve("ENG-5")
    monkeypatch.setenv("LINEAR_API_KEY", "k")
    assert resolve("eng-5") == ("linear", "ENG-5")
    for k, v in (("JIRA_BASE_URL", "u"), ("JIRA_EMAIL", "e"), ("JIRA_API_TOKEN", "t")):
        monkeypatch.setenv(k, v)
    with pytest.raises(TrackerError, match="could be Linear or Jira"):
        resolve("ENG-5")
    assert resolve("ENG-5", "jira") == ("jira", "ENG-5")
