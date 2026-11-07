import json
import random
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ticket_quality.cli import app, install_skills_to
from ticket_quality.eval_mock import respond
from ticket_quality.standard import load_standard

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evals" / "ticket-writing"
runner = CliRunner()


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ticket_quality.judge.pick_backend", lambda backend="auto": None)  # never call a model
    monkeypatch.chdir(ROOT / "tests")  # keep the repo's .env out of these runs


def test_check_exit_codes_and_json():
    ok = runner.invoke(app, ["check", str(ROOT / "examples" / "good-story.md")])
    assert ok.exit_code == 0 and "PASS" in ok.output
    bad = runner.invoke(app, ["check", str(ROOT / "examples" / "vague-story.md"), "--format", "json"])
    assert bad.exit_code == 1
    data = json.loads(bad.output)
    assert data["verdict"] == "FAIL" and data["judged"] is False


def test_check_stdin_and_unknown_ref():
    r = runner.invoke(app, ["check", "-", "--title", "Send reminders 3 days after due"],
                      input="## Summary\nBookkeepers chase payments by hand.\n\n## Acceptance criteria\n- [ ] reminder sent\n")
    assert r.exit_code == 0, r.output
    assert runner.invoke(app, ["check", "not-a-file.md"]).exit_code == 2


def test_install_skills_copies_current_guide(tmp_path):
    paths = install_skills_to(tmp_path)
    std = load_standard()
    for p in paths:
        assert (p / "SKILL.md").is_file()
        assert (p / "writer-guide.md").read_text() == std.writer_guide_path.read_text()
        front = (p / "SKILL.md").read_text().split("---")[1]
        assert re.search(r"(?m)^name: [a-z-]+$", front) and re.search(r"(?m)^description: .{50,}", front)


@pytest.mark.parametrize("path", ["standard/writer-guide.md", "evals/ticket-writing/prompts/seeded_inline_detail.md",
                                  "evals/ticket-writing/prompts/writer-guide-v1.md",
                                  "evals/ticket-writing/prompts/writer-guide-v2.md"])
def test_prompts_are_safe_as_jinja_templates(path):
    # The eval suite renders these with Jinja; a stray {{, {% or {# would break or change them.
    text = (ROOT / path).read_text()
    assert not re.search(r"\{\{|\{%|\{#", text)


def test_mock_writer_follows_the_guide():
    guide = load_standard().writer_guide_path.read_text()
    out = respond(system=guide, user="<request>Can we add a CSV export for our bookkeepers?</request>",
                  rng=random.Random(1))["ticket_markdown"]
    assert "<summary>Agent context</summary>" in out


def test_suite_loads_and_builds_cases():
    from llm_evals.engine import build_cases
    from llm_evals.suite import load_suite

    suite = load_suite(SUITE)
    cases = build_cases(suite)
    assert len(cases) == 72
    assert all("ask" in c.input for c in cases)


@pytest.mark.slow
def test_mock_gate_rolls_back_the_seeded_variant(tmp_path):
    proc = subprocess.run(
        ["llm-evals", "gate", str(SUITE), "--candidate", "versions/seeded_inline_detail.yaml",
         "--provider", "mock", "--skip-judges", "--db", str(tmp_path / "e.sqlite"), "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 2, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "ROLLBACK" in (tmp_path / "report.md").read_text()


@pytest.mark.slow
def test_mock_gate_runs_with_judges_and_pairwise(tmp_path):
    # Without --skip-judges the checklist and pairwise judges load their templates
    # from standard/judge/; a missing or misnamed template fails here, not in CI.
    proc = subprocess.run(
        ["llm-evals", "gate", str(SUITE), "--candidate", "versions/seeded_inline_detail.yaml",
         "--provider", "mock", "--limit", "6", "--db", str(tmp_path / "e.sqlite"), "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode in (0, 1, 2), proc.stderr[-2000:]
    assert "| checklist |" in (tmp_path / "report.md").read_text()


@pytest.mark.parametrize("keyword, criterion", [
    ("api keys", "An integration partner can create an API key from the Developer settings page."),
    ("wcag 2.1 aa", "The invoice editor meets WCAG 2.1 level AA."),
    ("named tax rate", 'A bookkeeper can create a tax rate with a name, such as "State sales tax 7%".'),
    ("paid invoices", "A paid invoice syncs within 15 minutes."),
    ("0-30", "The statement groups invoices into 0-30, 31-60 and 61-90 days."),
    ("approv", "A freelancer can send an estimate to a customer for approval."),
    ("overdue", "A bookkeeper can turn automatic overdue-invoice email reminders on."),
    ("read-only", "If all 3 retries fail, the workspace becomes read-only."),
])
def test_covers_ask_matches_word_forms(keyword, criterion):
    from ticket_quality.evals_plugin import keyword_in

    assert keyword_in(keyword, [criterion])


def test_covers_ask_needs_the_words_in_one_criterion():
    from ticket_quality.evals_plugin import keyword_in

    assert not keyword_in("named tax rate", ["A tax rate can be created", "Each has a name"])


def test_live_guide_is_the_promoted_version():
    # current.yaml (the baseline) and the archived v2 must hash the same until the guide changes again;
    # update this test (and archive the old guide) when you promote a new one.
    from llm_evals.runners.manifest import load_manifest

    current = load_manifest(SUITE / "versions" / "current.yaml", SUITE)
    v2 = load_manifest(SUITE / "versions" / "v2.yaml", SUITE)
    assert current.id == v2.id
