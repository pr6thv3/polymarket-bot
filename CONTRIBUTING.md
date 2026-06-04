# Contributing to polymarket-bot

Thanks for your interest! This guide covers how to contribute effectively.

---

## Development Setup

```bash
git clone https://github.com/pr6thv3/polymarket-bot.git
cd polymarket-bot
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your credentials. **Never commit `.env`.**

## Running Tests

```bash
# Full suite — must be green before any PR
python -m pytest tests/ -v

# Individual modules
python -m pytest tests/test_market_making.py -v
python -m pytest tests/test_news_fetcher.py -v
python -m pytest tests/test_signal_model.py -v
python -m pytest tests/test_ai_signals.py -v
```

**All 407 tests must pass.** No exceptions.

## Code Style

- **Python 3.11+** — use modern syntax (match statements, type unions, etc.)
- **Type hints** on all public functions and class attributes
- **Docstrings** on all public classes and methods (Google style)
- **async/await** for all I/O-bound operations (API calls, WebSocket handling)
- **Max line length**: 100 characters
- **Imports**: stdlib → third-party → local, grouped with blank lines

## Project Structure

```
core/       → Order lifecycle, execution, risk management
data/       → Market scanning, news fetching, signal modeling, whale tracking
strategies/ → Trading strategies (base class + implementations)
utils/      → Metrics, alerts, logging, helpers
tests/      → Pytest test suite (conftest.py for shared fixtures)
```

## Adding a New Strategy

1. Create `strategies/your_strategy.py` inheriting from `strategies.base.Strategy`
2. Implement `async def run_cycle(self) -> StrategyResult`
3. Add config section in `config.yaml` under `strategies:`
4. Wire into `main.py` with an `_init_your_strategy()` method
5. Add tests in `tests/test_your_strategy.py`
6. Update `CHANGELOG.md` and `README.md`

## Pull Request Process

1. Create a feature branch: `git checkout -b feat/your-feature`
2. Make changes with clear, atomic commits
3. Ensure all 407+ tests pass
4. Add tests for any new functionality
5. Update documentation (README, CHANGELOG, config.yaml comments)
6. Open a PR against `main` with a clear description

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add cross-exchange hedging strategy
fix: correct order_store API call in ai_signals
docs: update README with Phase 5 status
test: add edge case tests for Brier score tracker
refactor: extract common position sizing logic
```

## Security

- **Never commit `.env`**, API keys, wallet private keys, or tokens
- **Never log credentials** — use `***` masking in log output
- **Report vulnerabilities** privately — see SECURITY.md

## Questions?

Open an issue with the `question` label.
