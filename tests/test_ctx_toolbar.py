"""Unit tests for the persistent context toolbar."""

from clio.cli_repl import ClioREPL


class FakeAgent:
    def __init__(self, used=4800, model="qwen3-coder-unsloth:30b"):
        self._used = used
        self.current_model = model

    def context_usage(self):
        return self._used


def make_repl(used=4800, window=32768, model="qwen3-coder-unsloth:30b"):
    repl = object.__new__(ClioREPL)
    repl.agent = FakeAgent(used=used, model=model)
    repl._ctx_window = window
    return repl


class TestCtxMeterText:
    def test_resolved_window(self):
        style, text = make_repl()._ctx_meter_text()
        assert "15%" in text
        assert "4,800 / 32,768 tok" in text
        assert "qwen3-coder-unsloth:30b" in text
        assert "~" not in text
        assert style == "fg:#666666"

    def test_provisional_before_first_response(self):
        # Window not yet resolved: falls back to known table, marked with ~
        _, text = make_repl(window=None)._ctx_meter_text()
        assert "%~" in text
        assert "262,144" in text  # qwen3-coder known-table value

    def test_provisional_unknown_model_uses_default(self):
        _, text = make_repl(window=None, model="mystery:1b")._ctx_meter_text()
        assert "32,768" in text

    def test_warning_colors(self):
        style, _ = make_repl(used=24000)._ctx_meter_text()  # 73%
        assert style == "fg:ansiyellow"
        style, _ = make_repl(used=31000)._ctx_meter_text()  # 95%
        assert style == "fg:ansired"

    def test_caps_at_100_percent(self):
        _, text = make_repl(used=99999)._ctx_meter_text()
        assert "100%" in text

    def test_toolbar_returns_fragments(self):
        result = make_repl()._context_toolbar()
        assert isinstance(result, list) and len(result) == 1
        style, text = result[0]
        assert text.startswith(" ctx [")

    def test_toolbar_never_raises(self):
        repl = object.__new__(ClioREPL)  # no agent attribute at all
        assert repl._context_toolbar() == []
