# Security Policy

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

Instead, email **preethve.b@gmail.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

You should receive a response within 48 hours. If the issue is confirmed, we will work on a fix and coordinate disclosure.

## Sensitive Data Handling

This project handles highly sensitive data:

- **Polygon wallet private keys** — stored in `.env`, never committed
- **Polymarket API credentials** — stored in `.env`, never committed
- **OpenAI API keys** — stored in `.env`, never committed
- **Telegram bot tokens** — stored in `.env`, never committed

### Rules

1. **Never commit `.env`** — it is in `.gitignore` and must stay that way
2. **Never log raw credentials** — all log output must mask secrets with `***`
3. **Never hardcode credentials** in source code, config files, or test fixtures
4. **`.env.example`** contains only placeholder values with descriptions — no real keys

## Supported Versions

| Version | Phase | Supported |
|---------|-------|-----------|
| 0.4.x | Phase 4 (current) | ✅ Active |
| 0.3.x | Phase 3 | ✅ |
| 0.2.x | Phase 2 | ✅ |
| 0.1.x | Phase 1 | ✅ |

## Best Practices

- Use `python-dotenv` to load environment variables — never read `.env` directly
- Rotate API keys if they may have been exposed
- Use minimal token scopes (e.g., `repo` only for GitHub, trade-only for Polymarket)
- Keep `pip` dependencies updated: `pip install --upgrade -r requirements.txt`
