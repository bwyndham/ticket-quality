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
                      input="## Why\nBookkeepers chase payments by hand.\n\n## Summary\nReminders go out "
                            "automatically.\n\n## Acceptance criteria\n- [ ] reminder sent\n")
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
                                  "evals/ticket-writing/prompts/writer-guide-v2.md",
                                  "evals/ticket-writing/prompts/writer-guide-v3.md"])
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


def test_coverage_counts_only_acceptance_criteria_and_bug_fields():
    # llm-evals' requirements_covered, configured in suite.yaml: a requirement pasted
    # into the summary isn't covered until a criterion states it.
    from llm_evals.engine import build_cases, build_checks
    from llm_evals.suite import load_suite
    from llm_evals.types import Result

    suite = load_suite(SUITE)
    check = next(c for c in build_checks(suite.model_copy(update={"checks": [
        c for c in suite.checks if c.name == "requirements_covered"]})))
    case = next(c for c in build_cases(suite) if (c.source or {}).get("atoms") and not c.source.get("hinted_atom_ids"))
    phrases = [a["text"] for a in case.source["atoms"]]
    def result(summary, ac):
        out = {"summary": summary, "acceptance_criteria": ac, "steps_to_reproduce": [], "expected": "", "actual": ""}
        return Result(run_id="r", case_id=case.id, version_id="v", sample_idx=0, output=out)
    assert not check.score(case, result(" ".join(phrases), ["Something else happens"]), None).passed
    assert check.score(case, result("", phrases), None).passed



def test_live_guide_is_the_promoted_version():
    # current.yaml (the baseline) and the archived v2 must hash the same until the guide changes again;
    # update this test (and archive the old guide) when you promote a new one.
    from llm_evals.runners.manifest import load_manifest

    current = load_manifest(SUITE / "versions" / "current.yaml", SUITE)
    v3 = load_manifest(SUITE / "versions" / "v3.yaml", SUITE)
    assert current.id == v3.id
