# Source Contracts

Source contracts pin the official venue fields consumed by the research adapters.

Each contract records:

- official source URL;
- retrieval timestamp;
- contract ID/version;
- required JSON paths and types;
- alternative field groups where venue payloads support more than one complete shape;
- sanitized fixture response.

## Local fixture verification

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
```

This is deterministic and safe for normal CI.

## Live verification

The live probe is manual/scheduled in GitHub Actions. It checks official read-only
surfaces against the pinned contracts. It must not be required for fork pull requests,
because public contributors should not need secrets or reliable venue connectivity.

If a consumed field is missing, renamed, or type-changed, the live job fails closed and
the contract version must be manually reviewed before promotion.
