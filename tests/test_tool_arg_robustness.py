"""Tool execution must survive bad arguments instead of crashing the turn."""

import asyncio

from clio.agent.tools import Tools


def run(coro):
    return asyncio.run(coro)


class TestArgRobustness:
    def test_hallucinated_extra_kwarg_returns_error_not_raises(self):
        # The exact live failure: model called read_file(path=..., offset=...)
        tools = Tools()
        result = run(tools.execute_tool("read_file", {"path": "x.py", "offset": 100}))
        assert result.startswith("Error:")
        assert "offset" in result
        assert "path" in result  # tells the model the valid param

    def test_missing_required_param_returns_error(self):
        tools = Tools()
        result = run(tools.execute_tool("read_file", {}))
        assert result.startswith("Error:")
        assert "missing" in result.lower()
        assert "path" in result

    def test_unknown_tool(self):
        tools = Tools()
        assert run(tools.execute_tool("frobnicate", {"x": 1})).startswith("Error: Unknown tool")

    def test_non_dict_arguments(self):
        tools = Tools()
        assert run(tools.execute_tool("read_file", ["x"])).startswith("Error:")

    def test_runtime_exception_wrapped_not_raised(self):
        # read_file on a nonexistent path returns an error string already, but
        # confirm no exception escapes execute_tool for any reason.
        tools = Tools()
        result = run(tools.execute_tool("read_file", {"path": "/no/such/file/xyz123"}))
        assert isinstance(result, str)  # did not raise

    def test_valid_call_still_works(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hi there")
        tools = Tools()
        result = run(tools.execute_tool("read_file", {"path": str(f)}))
        assert "hi there" in result

    def test_restricted_context_still_enforced_first(self):
        tools = Tools(allowed_tools={"read_file"})
        # even with valid args, a disallowed tool is refused
        result = run(tools.execute_tool("write_file", {"path": "x", "content": "y"}))
        assert "not available" in result
