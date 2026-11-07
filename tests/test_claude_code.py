import json
import subprocess
from types import SimpleNamespace

import pytest
from llm_evals.runners.errors import FatalRunError, InfraError

from ticket_quality.claude_code import ClaudeCodeProvider, use_for_llm_evals


def ok(text="hello", **extra):
    body = {"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn",
            "session_id": "s1", "usage": {"input_tokens": 3, "cache_creation_input_tokens": 600,
                                          "cache_read_input_tokens": 100, "output_tokens": 9}, **extra}
    return SimpleNamespace(stdout=json.dumps(body), stderr="", returncode=0)


def err(result, status=None):
    return SimpleNamespace(stdout=json.dumps({"type": "result", "subtype": "success", "is_error": True,
                                              "result": result, "api_error_status": status}), stderr="", returncode=1)


def provider(*outcomes, calls=None):
    seq = list(outcomes)

    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        item = seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    return ClaudeCodeProvider(binary="/bin/claude", runner=run, sleep=lambda s: None)


def test_command_env_and_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    calls = []
    p = provider(ok("the ticket"), calls=calls)
    r = p.complete(model="claude-sonnet-5-5", system="SYS", user="USER", params={"max_tokens": 4000, "effort": "low"})
    assert (r.text, r.input_tokens, r.output_tokens, r.stop_reason) == ("the ticket", 703, 9, "end_turn")
    cmd, kw = calls[0]
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS" and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5" and cmd[cmd.index("--effort") + 1] == "low"
    assert kw["input"] == "USER"
    assert "ANTHROPIC_API_KEY" not in kw["env"]  # must bill the subscription, not the key
    assert kw["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "4000"


def test_transient_errors_retry_then_succeed():
    p = provider(err("API Error: Overloaded", 529), subprocess.TimeoutExpired("claude", 1), ok("fine"))
    assert p.complete(model="m", system=None, user="u", params={}).text == "fine"


def test_persistent_transient_errors_become_infra():
    p = provider(*[err("Overloaded", 529)] * 4)
    with pytest.raises(InfraError):
        p.complete(model="m", system=None, user="u", params={})


@pytest.mark.parametrize("outcome, match", [
    (err("Claude AI usage limit reached|1762560000"), "usage limit"),
    (err("Invalid API key · Please run /login", 401), "authenticated"),
    (err("model: claude-nope not found", 404), "rejected"),
])
def test_fatal_errors_abort_the_run(outcome, match):
    with pytest.raises(FatalRunError, match=match):
        provider(outcome).complete(model="m", system=None, user="u", params={})


def test_patches_llm_evals_provider(monkeypatch):
    import llm_evals.runners.providers.anthropic as mod

    monkeypatch.setattr(mod, "AnthropicProvider", mod.AnthropicProvider)  # restored after the test
    use_for_llm_evals()
    assert mod.AnthropicProvider is ClaudeCodeProvider
