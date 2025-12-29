#!/usr/bin/env python3
"""Redaction scanner for public demo repositories.

This script is intentionally lightweight and conservative. It scans the repo for
high-risk patterns that may indicate secret leakage or private endpoint exposure.

Usage:
    python tools/redaction_scan.py

Exit codes:
    0: No findings
    1: Findings detected
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    preview: str
    rule: str


REPO_ROOT = Path(__file__).resolve().parents[1]

# Files we usually do not want to scan (vendored/lock files can be very noisy).
IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}

IGNORE_FILES = {
    "uv.lock",
    "redaction_scan.py",
}

RULES: list[tuple[str, re.Pattern[str]]] = [
    # Authorization header with a non-trivial bearer token
    ("auth_header", re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE)),
    # JWT-like tokens embedded in code/config (very common leakage vector)
    ("jwt_like", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # Private key material
    ("private_key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # Connection strings with credentials (user:pass@host)
    ("conn_with_creds", re.compile(r"\b(mongodb|postgres|redis)://[^\\s/:]+:[^\\s@]+@", re.IGNORECASE)),
    # Internal codenames / legacy identifiers should not appear in a public repo
    ("internal_codename", re.compile(r"\b(cw|flc|cbx|cbe|corebe)\b", re.IGNORECASE)),
]


def _should_ignore(path: Path) -> bool:
    if path.name in IGNORE_FILES:
        return True
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False


def scan_repo(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if _should_ignore(file_path):
            continue

        # Only scan text-like files
        if file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for idx, line in enumerate(content, start=1):
            for rule_name, pattern in RULES:
                if pattern.search(line):
                    preview = line.strip()
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    findings.append(
                        Finding(
                            path=str(file_path.relative_to(root)),
                            line_no=idx,
                            preview=preview,
                            rule=rule_name,
                        )
                    )
    return findings


def main() -> int:
    findings = scan_repo(REPO_ROOT)
    if not findings:
        print("✅ Redaction scan passed: no findings.")
        return 0

    print("❌ Redaction scan failed: potential leakage patterns detected.")
    for f in findings[:200]:
        print(f"- [{f.rule}] {f.path}:{f.line_no} :: {f.preview}")

    if len(findings) > 200:
        print(f"... truncated ({len(findings)} total findings)")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())


