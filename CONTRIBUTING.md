# Contributing

Thanks for helping improve the prediction-market research lab. The supported public
project is read-only research and paper evidence. Live trading is not an accepted
contribution target unless a future governance decision explicitly opens that gate.

## Development setup

```bash
git clone https://github.com/pr6thv3/polymarket-bot.git
cd polymarket-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Do not add trading credentials to `.env` for normal development. The fixture and test
workflow must run without secrets.

## Required checks

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe tools/software_health_report.py
```

All checks must pass before a pull request is ready.

## Contribution areas

Good contributions:

- source-contract fixtures and validation improvements;
- mapping-candidate tooling;
- manual mapping-review evidence;
- replay/evidence-pack quality;
- docs, examples, and contributor experience;
- tests that strengthen the read-only safety boundary.

Gated contributions:

- strategy economics;
- fee/reward crediting;
- live execution;
- authenticated trading surfaces;
- WebSocket trading integrations.

These require the proof gates in `docs/proof_standard.md`.

## Safety rules

- Never commit `.env`, private keys, API secrets, wallet mnemonics, or account data.
- Research tools must not import `core`, `strategies`, `data`, or `main.py`.
- Do not call `core/client.py create_order` or live paths in `core/executor.py`.
- Keep `execution.dry_run: true`.
- Keep execution-capable strategies disabled in `config.yaml`.
- Do not describe a strategy as profitable without a Gate 2 evidence pack.

## Pull request process

1. Create a focused branch.
2. Add tests for behavior changes.
3. Update docs when public behavior or proof gates change.
4. Run the required checks.
5. Fill out the pull request safety checklist.

## Commit messages

Use clear, scoped commits. Conventional Commit prefixes are welcome:

```text
feat: add fixture-only replay example
fix: reject incomplete mapping review evidence
docs: clarify no-go live trading gate
test: cover software health report output
```
