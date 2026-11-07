import json
from pathlib import Path

from llm_evals.judges.base import load_rubric
from llm_evals.runners.prompt import render_template
from llm_evals.runners.providers.base import FakeProvider

from ticket_quality.judge import applicable_items, judge_ticket, make_client
from ticket_quality.standard import load_standard
from ticket_quality.ticket import parse_ticket
from ticket_quality.validate import validate

STD = load_standard()
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fake_client(answer_for, tmp_path):
    def respond(call):
        payload = json.loads(call["user"].split("```json\n", 1)[1].rsplit("```", 1)[0].replace("\\u0060", "`"))
        items = [{"id": i["id"], **answer_for(i["id"])} for i in payload["items"]]
        respond.payloads.append(payload)
        return json.dumps({"items": items})
    respond.payloads = []
    client = make_client("claude-sonnet-5-5", provider=FakeProvider(default=respond), cache_path=tmp_path / "c.sqlite")
    return client, respond.payloads


def test_rubric_loads_in_llm_evals_and_prompts_render():
    items = load_rubric(STD.rubric_path)
    assert [i["id"] for i in items] == [i.id for i in STD.rubric]
    render_template(str(STD.judge_system_path), {})
    render_template(str(STD.judge_user_path), {})


def test_applicability_filters():
    story = parse_ticket((EXAMPLES / "good-story.md").read_text())
    bug = parse_ticket((EXAMPLES / "good-bug-linear.md").read_text())
    story_ids = {i.id for i in applicable_items(STD, story, has_ask=False)}
    assert "bug_reproducible" not in story_ids and "no_unstated_requirements" not in story_ids
    assert "bug_reproducible" in {i.id for i in applicable_items(STD, bug, has_ask=False)}
    assert "no_unstated_requirements" in {i.id for i in applicable_items(STD, story, has_ask=True)}


def test_no_answers_become_findings_with_severity_and_fix(tmp_path):
    def answer(item_id):
        if item_id == "self_contained":
            return {"answer": "no", "reason": "Says 'as discussed'.", "fix": "Spell out the decision."}
        if item_id == "scope_bounded":
            return {"answer": "no", "reason": "No out of scope.", "fix": ""}
        return {"answer": "yes", "reason": "ok", "fix": ""}

    client, payloads = fake_client(answer, tmp_path)
    t = parse_ticket((EXAMPLES / "good-story.md").read_text())
    findings = judge_ticket(t, STD, client, ask="please add reminders")
    by = {f.rule: f for f in findings}
    assert by["self_contained"].severity == "error" and by["self_contained"].fix == "Spell out the decision."
    assert by["scope_bounded"].severity == "warn"
    assert payloads[0]["ask"] == "please add reminders"
    assert payloads[0]["ticket"]["agent_context_style"] == "collapsed"


def test_judge_failure_leaves_rules_standing(tmp_path):
    client = make_client(provider=FakeProvider(default="not json at all"), cache_path=tmp_path / "c.sqlite")
    t = parse_ticket((EXAMPLES / "good-story.md").read_text())
    report = validate(t, STD, judge_client=client)
    assert report.judged is False and report.judge_note.startswith("judge skipped")
    assert report.verdict() == "PASS"
