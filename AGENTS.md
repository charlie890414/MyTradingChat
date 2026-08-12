# Repository Guide

## Setup And Checks

- Python 3.11+ is required. `uv.lock` is committed; use `uv sync --dev` for the locked development environment and run tools as `uv run ...`.
- Focused test: `uv run pytest tests/test_cli.py::test_cmd_init`. Normal `uv run pytest` excludes tests marked `network` via `pyproject.toml`; opt in with `uv run pytest -m network`. Live tests load root `.env`, require internet, and conditionally need provider credentials.
- Full local verification: `uv run ruff check .`, `uv run ruff format --check .`, then `uv run pytest`.
- `uv run pre-commit run --all-files` is not a read-only check: its Ruff and whitespace hooks fix files before running the full non-network pytest suite.
- There is no repository CI workflow; local checks and pre-commit are the executable quality gates.

## Runtime Architecture

- `trading-debate` and `python -m trading_debate` both enter `trading_debate.cli:main`. The CLI loads only the root `.env` and defaults to `data/research.sqlite3`.
- `cli.py` orchestrates commands; `connectors/` owns external providers; `context.py` builds role-specific views; `quality.py` and `summaries.py` validate contributions; `db.py` owns persistence; `render.py` renders from SQLite; `web.py` serves the historical UI.
- `finance.py` and top-level exports in `__init__.py` are compatibility surfaces used by callers/tests. Preserve re-exports and patchable module attributes when moving connector or symbol code.
- `db.connect()` creates directories/schema, enables WAL and foreign keys, and runs migrations on every connection. Test database changes with `tmp_path`; never use a database under `data/` in tests.
- Evidence fetches are immutable batches. Contexts and reports select the latest `completed` or `partial` batch, rather than mixing evidence from multiple fetches. `render` updates run status but does not write Markdown; only `export --output ...` creates a report file.
- Runtime databases and exports belong under ignored `data/` and `reports/`; do not commit them or treat existing local databases as fixtures.

## Research Workflow Boundary

- Stock-analysis requests are not ordinary CLI development tasks: load `.agents/skills/trading-debate/SKILL.md` and its stage references. That workflow requires Traditional Chinese output, `uv run python -m trading_debate.cli ...`, preservation of one generated run ID, and immediate persistence of each stage.
- During a research workflow, never pass `--db`; every stage must use the default `data/research.sqlite3`. Alternate paths split history from `search` and the web UI.
- Provider failures and unavailable optional credentials must become explicit evidence gaps, never invented evidence. `FINNHUB_API_KEY`, `FINMIND_TOKEN`, and `FRED_API_KEY` are optional; SEC access requires a contactable `SEC_USER_AGENT`.
- Wealthfolio requests follow the separate `.agents/skills/wealthfolio/SKILL.md` MCP workflow; do not mix its portfolio mutations with this repository's research SQLite data.

## Change Constraints

- Keep network-backed unit tests deterministic. `tests/conftest.py` globally blocks Taiwan company-profile network lookup; mock provider calls in ordinary tests and reserve real services for `tests/test_connectors_live.py`.
- Ruff targets Python 3.11, 88 columns, double quotes, and import sorting. Tests intentionally relax `E501`, `SIM117`, and `PT006`; `dump_evidence.py` is excluded from Ruff.
- Package HTML templates and CSS are declared as setuptools package data. Verify changes to the archive UI with `uv run pytest tests/test_web.py`; the container serves port `8765` and needs write permission for the bind-mounted `data/` directory and SQLite WAL files.
