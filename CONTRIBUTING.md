# Contributing

## Development Setup

1. Clone the repository.
2. Create and activate a Python environment.
3. Install Dioptas and dependencies:

```bash
pip install -e .
pip install -e .[dev]
```

## Running Locally

```bash
python -m dioptas_batch_gui
```

## Pull Requests

1. Create a feature branch.
2. Keep changes focused and include tests when possible.
3. Update documentation and `CHANGELOG.md` when behavior changes.
4. Open a PR with a clear description and verification steps.

## Code Style

- Prefer clear, small functions.
- Keep GUI logic responsive (avoid blocking on main thread).
- Use `ruff` formatting/linting defaults configured in `pyproject.toml`.
