# Collector start failure — 2026-06-22 20:55 UTC

Attempted command:

```bash
cd /c/Users/Preethve/polymarket-bot && .venv/Scripts/python.exe tools/collect_backtest_data.py --duration-minutes 1440
```

Result: exited with code 1 before data collection started.

Traceback:

```text
Traceback (most recent call last):
  File "C:\Users\Preethve\polymarket-bot\tools\collect_backtest_data.py", line 17, in <module>
    from utils.helpers import load_config
ModuleNotFoundError: No module named 'utils.helpers'; 'utils' is not a package
```

Immediate recovery attempted without source changes: restart collector with `PYTHONPATH=.` so repo-local packages resolve when running a script from `tools/`.
