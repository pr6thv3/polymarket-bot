# Security Policy

## Reporting a vulnerability

Do not report security vulnerabilities through public GitHub issues.

Email **preethve.b@gmail.com** with:

- vulnerability description;
- reproduction steps;
- potential impact;
- suggested fix, if available.

## Current security posture

The supported public project is read-only research. Live trading remains `NO-GO`.

The research runtime must not require or load:

- wallet private keys;
- exchange trading credentials;
- authenticated trading endpoints;
- live order paths;
- deposit or withdrawal permissions.

## Sensitive data rules

- Never commit `.env`.
- Never commit private keys, wallet mnemonics, API secrets, passphrases, or account data.
- Never log raw credentials.
- Never add credentials to fixtures, docs, screenshots, issue bodies, or tests.
- Keep `.env.example` research-safe.
- Use `.env.live.example` only as a documented legacy warning surface.

## Read-only boundary

Research code must stay isolated from:

- `core/client.py create_order`;
- live order paths in `core/executor.py`;
- authenticated WebSocket or account endpoints;
- strategy code that can place or amend orders.

The safety boundary is verified by tests and `tools/software_health_report.py`.

## Supported versions

Until a formal release is cut, the `main` branch is the supported development line for
read-only research tooling only.
