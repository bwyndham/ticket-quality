"""Run model calls through the `claude` CLI, billed to your Claude subscription (Pro/Max)
instead of an API key.

`ClaudeCodeProvider` implements llm-evals' Provider protocol (`complete(model=, system=,
user=, params=)`) by running one headless Claude Code call per request:

    claude -p --system-prompt <system> --tools "" --output-format json --model <model> ...

- The system prompt *replaces* Claude Code's own, tools are off, settings, MCP servers,
  skills and session history are skipped, and it runs in an empty temp folder, so the
  model sees what the API would: your system prompt and the user message.
- ANTHROPIC_API_KEY is removed from the child's environment; otherwise the CLI would
  bill the key instead of your subscription.
- `params["max_tokens"]` goes in as CLAUDE_CODE_MAX_OUTPUT_TOKENS, `params["effort"]` as --effort.
- Rate limits and overload are retried with backoff, then reported as INFRA (the sample
  is excluded, not failed). Hitting the subscription's usage limit aborts the run with
  a clear message: retrying wouldn't help until the limit resets.

Costs in reports are list-price equivalents from token counts; nothing is billed per call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from llm_evals.runners.errors import FatalRunError, InfraError
from llm_evals.runners.providers.base import ProviderResponse

_LIMIT_WORDS = ("usage limit", "limit reached", "out of extra usage", "weekly limit", "session limit")


class ClaudeCodeProvider:
    def __init__(self, max_retries: int = 3, timeout: float = 300.0, *, binary: str | None = None,
                 runner: Any = subprocess.run, sleep: Any = time.sleep, **_: Any) -> None:
        self.binary = binary or os.environ.get("CLAUDE_BIN") or shutil.which("claude")
        if not self.binary:
            raise FatalRunError("the `claude` CLI isn't on PATH; install Claude Code and run `claude auth login`")
        self.max_retries = max_retries
        self.timeout = timeout
        self._run = runner
        self._sleep = sleep
        self._cwd = tempfile.mkdtemp(prefix="claude-provider-")

    def command(self, *, model: str, system: str | None, params: dict[str, Any]) -> list[str]:
        cmd = [self.binary, "-p", "--output-format", "json", "--model", model, "--tools", "",
               "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
               "--disable-slash-commands", "--system-prompt", system or "You are a helpful assistant."]
        if params.get("effort"):
            cmd += ["--effort", str(params["effort"])]
        return cmd

    def env(self, params: dict[str, Any]) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        if params.get("max_tokens"):
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(params["max_tokens"])
        return env

    def complete(self, *, model: str, system: str | None, user: str, params: dict[str, Any]) -> ProviderResponse:
        cmd, env = self.command(model=model, system=system, params=params), self.env(params)
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                proc = self._run(cmd, input=user, capture_output=True, text=True, env=env,
                                 cwd=self._cwd, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                last = f"claude CLI timed out after {self.timeout:.0f}s"
            else:
                outcome = self._parse(proc)
                if isinstance(outcome, ProviderResponse):
                    return outcome
                last = outcome
            if attempt < self.max_retries:
                self._sleep(min(60.0, 5.0 * 2 ** attempt))
        raise InfraError(f"claude CLI failed after {self.max_retries + 1} attempts: {last}")

    def _parse(self, proc: Any) -> ProviderResponse | str:
        """A response, or a retryable error message. Raises for errors that won't go away."""
        try:
            data = json.loads(proc.stdout or "")
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            msg = (proc.stderr or proc.stdout or "").strip()[:500] or f"exit code {proc.returncode}"
            self._raise_if_fatal(msg)
            return msg
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            msg = str(data.get("result") or data.get("subtype") or "error")[:500]
            status = data.get("api_error_status")
            self._raise_if_fatal(msg, status)
            return f"{status or ''} {msg}".strip()
        usage = data.get("usage") or {}
        input_tokens = sum(int(usage.get(k) or 0) for k in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return ProviderResponse(text=data.get("result") or "", input_tokens=input_tokens,
                                output_tokens=int(usage.get("output_tokens") or 0),
                                request_id=data.get("session_id"), stop_reason=data.get("stop_reason"))

    @staticmethod
    def _raise_if_fatal(msg: str, status: Any = None) -> None:
        low = msg.lower()
        if any(w in low for w in _LIMIT_WORDS):
            raise FatalRunError(f"Claude subscription usage limit reached; rerun after it resets ({msg})")
        if status in (401, 403) or "not logged in" in low or "please run /login" in low or "invalid api key" in low:
            raise FatalRunError(f"claude CLI isn't authenticated: run `claude auth login` ({msg})")
        if status in (400, 404) or ("model" in low and ("not found" in low or "invalid" in low)):
            raise FatalRunError(f"claude CLI rejected the request: {msg}")


def use_for_llm_evals() -> None:
    """Make llm-evals' `anthropic` provider (and its judge) go through the claude CLI."""
    import llm_evals.runners.providers.anthropic as anthropic_provider

    anthropic_provider.AnthropicProvider = ClaudeCodeProvider  # read at call time by llm-evals' CLI


def evals_main() -> None:  # pragma: no cover - thin entry point, exercised by hand
    """`ticket-evals`: llm-evals' CLI, with model calls on your Claude subscription.

    Every llm-evals command and flag works the same (gate, seeded, aa, estimate,
    calibration ...). Set TICKET_EVALS_BACKEND=api to use ANTHROPIC_API_KEY instead.
    """
    if os.environ.get("TICKET_EVALS_BACKEND", "claude-code") == "claude-code":
        use_for_llm_evals()
    from llm_evals.cli.main import app

    app()


__all__ = ["ClaudeCodeProvider", "evals_main", "use_for_llm_evals"]
