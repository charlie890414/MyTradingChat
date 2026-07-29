# Repository Guidelines

## Project Structure & Module Organization

`trading_debate/` contains the Python package and CLI: `cli.py` defines commands, `finance.py` and `fetchers.py` collect evidence, `db.py` persists SQLite data, and `render.py` produces Markdown reports. Keep reusable helpers in `utils.py` and expose public package functions through `__init__.py` where appropriate.

`tests/` contains pytest unit tests in `test_*.py` files. `.agents/skills/trading-debate/` holds the Codex workflow instructions; `.agents/skills/wealthfolio/` holds the Wealthfolio MCP advisor skill and its `references/` subfolder (tool catalogue and mutation-safety guardrails). Runtime SQLite databases belong in `data/`; generated reports belong in `reports/`. Both are intentionally ignored by Git.

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

Write pytest tests alongside related behavior in `tests/test_trading_debate.py` or a focused new `tests/test_<area>.py` file. Name tests `test_<behavior>`. Use `tmp_path` for databases and `unittest.mock.patch` for network-backed sources, so tests remain deterministic and do not require API keys. Add regression coverage for fixes and new CLI or persistence behavior.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects, such as `feat: add new news sources` and `feat(trading-debate): enhance equity research debate workflow`. Use concise imperative subjects with an optional scope. Keep commits focused. Pull requests should explain the user-visible change, list validation performed (for example, `pytest` and `ruff check .`), link related issues when available, and include sample output or screenshots for report/CLI presentation changes.

## Security & Configuration

Copy `.env.example` for local configuration and keep API keys only in `.env` or environment variables (`ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `FINMIND_TOKEN`). Never commit credentials, generated databases, or research reports.
