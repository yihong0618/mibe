# Repository Guidelines

## Project Structure & Module Organization
- `mibe.py`: main CLI and monitoring logic (Codex/Kimi log parsing, XiaoAi notification flow).
- `main.py`: minimal entry script placeholder; use `mibe.py` for real runtime behavior.
- `tests/`: pytest suite (`test_*.py`), including unit and integration-style checks.
- `config.toml.example`: sample runtime configuration for TTS messages and settings.
- Root docs: `README.md` / `README_EN.md` for setup and usage.

Keep new modules small and focused. If `mibe.py` grows, split by responsibility (e.g., config parsing, event parsing, notifier client) under a package directory.

## Build, Test, and Development Commands
Use `uv` for dependency management and execution.
- `make install`: install runtime + dev dependencies via `uv sync`.
- `make test`: run pytest (`uv run pytest -v`).
- `make test-cov`: run tests with coverage output and HTML report (`htmlcov/`).
- `make lint`: run `ruff check` and import-order checks.
- `make format`: apply `ruff format` and fix imports.
- `make check`: run lint + tests (good pre-PR baseline).
- `make run`: run `main.py` (placeholder).
- `make login` / `make monitor`: run the actual CLI workflows in `mibe.py`.

## Coding Style & Naming Conventions
- Python 3.12+ with 4-space indentation and type hints for public functions.
- Follow existing style: `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants, `PascalCase` for classes.
- Keep comments brief and intent-focused; prefer self-explanatory code.
- Format and lint with Ruff (`make format`, `make lint`). Pre-commit hooks also run Ruff and basic file checks.

## Testing Guidelines
- Frameworks: `pytest`, `pytest-asyncio`, `pytest-cov`.
- Naming is enforced in `pytest.ini`: files `test_*.py`, functions `test_*`, classes `Test*`.
- Add tests for behavior changes, especially log event parsing, config loading, and notifier side effects/error handling.
- Run `make test-cov` for non-trivial changes and inspect missing lines in the terminal report.

## Commit & Pull Request Guidelines
- History shows mostly short commits, often Conventional Commit style (for example, `feat: add kimi`). Prefer that format.
- Keep commit messages concise and scoped to one change.
- PRs should include: purpose, key changes, test results (`make check` output summary), and config/behavior examples when user-facing behavior changes.
- Update `README.md` or `config.toml.example` when CLI flags or configuration keys change.
