# Security Redaction (Public Demo)

This repository is a **sanitized portfolio showcase**. It is derived from a production-grade backend,
but intentionally modified so it can be safely published on GitHub.

## What is removed / redacted

- **Secrets**: API keys, signing secrets, access tokens, session secrets
- **Private endpoints**: internal domains, staging URLs, webhook endpoints
- **Customer / user data**: any real IDs, payloads, logs, and snapshots
- **Private repository references**: internal Git remotes and organization identifiers

## What is kept (for demonstration)

- **Architecture & layering**: API routers, domain services, schemas, error handling
- **Business domain (genericized)**: Channel / Session / User lifecycle and state patterns
- **AI capability (safe demo)**: agent-style module boundaries for caption/transcript workflows
- **CI/CD patterns**: lint/test/security scans + Docker build and an example push pipeline

## Safe configuration policy

- The repository includes only `env.example` (**placeholders only**).
- Local overrides must be stored in `env.local` (**must not be committed**).
- CI secrets must be provided via GitHub Actions **Secrets/Variables**.

## Automated leakage scan

We include a simple scanner: `tools/redaction_scan.py`.

It searches for common leakage patterns:
- `api_key`, `api_secret`, `token`, `password`, `Authorization: Bearer`
- `mongodb://`, `postgres://`, `redis://`
- hardcoded `http://` / `https://` private endpoints

Run it locally:

```bash
python tools/redaction_scan.py
```

## Notes

If you plan to fork or reuse this repository, you should:
- keep `DEMO_MODE=true` by default
- ensure external integrations are stubbed unless explicitly enabled
- run the leakage scan before every public push

