"""Tests for /model: direct typed switch, and the non-interactive fallback.

(The interactive arrow-key path is verified separately via a pty/pexpect
smoke test — it needs a real terminal.)"""

import asyncio
from types import SimpleNamespace

from clio.cli_repl import ClioREPL
from clio.config import ConfigManager


def make_repl():
    repl = object.__new__(ClioREPL)
    repl.config_manager = ConfigManager()
    switched = {}

    async def fake_switch(provider, model):
        if provider == "nope":
            raise ValueError(f"Unknown provider: {provider}")
        switched["to"] = (provider, model)

    repl.agent = SimpleNamespace(
        current_model="qwen3:30b-a3b",
        current_provider_name="local-gpu",
        switch_model=fake_switch,
    )
    repl._switched = switched
    return repl


def run(coro):
    return asyncio.run(coro)


class TestTypedSwitch:
    def test_direct_two_arg_switch(self):
        repl = make_repl()
        out = run(repl._cmd_model("openrouter deepseek/deepseek-v4-pro"))
        assert "Switched to" in out
        assert repl._switched["to"] == ("openrouter", "deepseek/deepseek-v4-pro")

    def test_invalid_provider_reports_error(self):
        repl = make_repl()
        out = run(repl._cmd_model("nope somemodel"))
        assert "Unknown provider" in out

    def test_switch_resets_ctx_window(self):
        repl = make_repl()
        repl._ctx_window = 999
        run(repl._cmd_model("openrouter deepseek/deepseek-v4-pro"))
        assert repl._ctx_window is None


class TestNonInteractiveFallback:
    def test_lists_models_when_not_a_tty(self, monkeypatch):
        # Force the non-tty branch so the picker is skipped in CI
        import clio.cli_repl as mod
        monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
        repl = make_repl()
        out = run(repl._cmd_model(""))
        assert "Switch with:" in out
        assert "local-gpu" in out


class TestSwitchAndReport:
    def test_success_message(self):
        repl = make_repl()
        out = run(repl._switch_and_report("anthropic", "claude-fable-5"))
        assert "claude-fable-5" in out and "anthropic" in out
