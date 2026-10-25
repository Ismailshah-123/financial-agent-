"""
tests.conftest
===============
Shared pytest fixtures.

Async tests run under `pytest-asyncio` in `auto` mode (see
`[tool.pytest.ini_options] asyncio_mode = "auto"` in pyproject.toml) —
every `async def test_...` is automatically treated as an asyncio test,
no `@pytest.mark.anyio` or explicit `anyio_backend` fixture needed.
Deliberately NOT also using the `anyio` pytest plugin's own test
collection (even though `anyio` is installed as an httpx dependency) —
running two async test plugins against the same test functions risks
double-execution or collection conflicts. `pytest-asyncio` alone is the
project's single source of truth for async test execution.
"""
