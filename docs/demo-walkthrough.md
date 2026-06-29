# Demo Walkthrough

This demo proves the repository can run the safe research checks from fixtures. It does
not require credentials and does not prove strategy profitability.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe tools/software_health_report.py
```

Expected artifacts:

- `reports/software_health_report.md`;
- `reports/software_health_report.json`.

Next research step:

```bash
.venv\Scripts\python.exe tools/generate_candidates.py --dry-run
```

Candidate output still requires manual semantic review before any replay claim.
