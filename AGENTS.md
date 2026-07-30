# Repository Guidelines

## Project Structure & Module Organization

`trading_debate/` contains the Python package and CLI: `cli.py` defines commands; `connectors/` collects evidence from Yahoo Finance, Google News RSS, Bing News RSS, Finnhub, FinMind, SEC EDGAR, and TWSE; `finance.py` is a compatibility facade that re-exports connectors and symbol utilities; `symbols.py` handles symbol normalization and Taiwan exchange resolution; `db.py` persists SQLite data; `models.py` holds shared data models; and `render.py` produces Markdown reports. Keep reusable helpers in `utils.py` and expose public package functions through `__init__.py` where appropriate.

`tests/` contains pytest unit tests in `test_*.py` files. `.agents/skills/trading-debate/` holds the agent workflow instructions; `.agents/skills/wealthfolio/` holds the Wealthfolio MCP advisor skill and its `references/` subfolder (tool catalogue and mutation-safety guardrails). Runtime SQLite databases belong in `data/`; generated reports belong in `reports/`. Both are intentionally ignored by Git.

## Build, Test, and Development Commands

Use Python 3.11 or newer. Install the package for local CLI development:

```powershell
python -m pip install -e .
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

The first command installs the `trading-debate` entry point; the second additionally installs development tooling. `pytest` runs the test suite. Run `ruff check .` before committing, and use `ruff format .` to apply the repository formatter.

## Coding Style & Naming Conventions

Follow Ruff's configured style: four-space indentation, double quotes, 88-character lines, and Python 3.11-compatible syntax. Use `snake_case` for modules, functions, variables, and CLI options; use `PascalCase` for classes. Prefer typed, small functions with explicit inputs and outputs. Keep external-source failures and optional credentials handled gracefully; do not invent evidence when a connector is unavailable.

## Testing Guidelines

Write pytest tests in focused `tests/test_<area>.py` files that match the module under test (for example, `tests/test_cli.py`, `tests/test_connectors.py`, `tests/test_db.py`, `tests/test_models.py`, `tests/test_symbols.py`, `tests/test_technicals.py`, and `tests/test_utils.py`). Place shared fixtures and helpers in `tests/conftest.py`. Name tests `test_<behavior>`; the file already provides module context, so avoid redundant module prefixes. Use `tmp_path` for databases and `unittest.mock.patch` for network-backed sources, so tests remain deterministic and do not require API keys. Add regression coverage for fixes and new CLI or persistence behavior.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects, such as `feat: add new news sources` and `feat(trading-debate): enhance equity research debate workflow`. Use concise imperative subjects with an optional scope. Keep commits focused. Pull requests should explain the user-visible change, list validation performed (for example, `pytest` and `ruff check .`), link related issues when available, and include sample output or screenshots for report/CLI presentation changes.

## Security & Configuration

Copy `.env.example` for local configuration and keep API keys only in `.env` or environment variables (`FINNHUB_API_KEY`, `FINMIND_TOKEN`). Google News RSS and Bing News RSS do not require credentials. Never commit credentials, generated databases, or research reports.
