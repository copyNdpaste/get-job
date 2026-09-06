#!/usr/bin/env python3
"""Scan publishable content without printing matched values or personal data."""

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[A-Z0-9]{16}|hooks\.slack\.com/services/[A-Za-z0-9/]+"
    r"|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"
)
PERSONAL_PATH = re.compile(r"/(?:Users|home)/[^/\s\"']+/")
PHONE = re.compile(r"(?<!\d)(?:01[016789]|\+82[- .]?10)[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
EMAIL = re.compile(r"[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})", re.I)
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def sensitive_path(name: str) -> bool:
    path = PurePosixPath(name)
    parts = set(path.parts)
    if name in {".env.example", "data/README.md", "data/.gitkeep"}:
        return False
    return (
        path.name == ".DS_Store"
        or path.name.startswith(".env")
        or bool(
            parts
            & {
                "data",
                "output",
                "secrets",
                ".auth",
                "playwright-profile",
                "node_modules",
                ".venv",
                ".cache",
                ".codex",
                ".agents",
            }
        )
        or path.name in {"credentials.json", "Thumbs.db", "Desktop.ini"}
        or path.name.startswith("service-account")
        or bool(re.search(r"\.(?:local|private)\.", path.name))
        or path.suffix.lower()
        in {
            ".db",
            ".sqlite",
            ".sqlite3",
            ".dump",
            ".sql",
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".har",
            ".log",
            ".mobileprovision",
            ".heapsnapshot",
        }
    )


def content_issues(data: bytes) -> set[str]:
    text = data.decode("utf-8", errors="replace")
    issues = set()
    if SECRET.search(text):
        issues.add("credential-signature")
    if PERSONAL_PATH.search(text):
        issues.add("personal-filesystem-path")
    if PHONE.search(text):
        issues.add("phone-number")
    for match in EMAIL.finditer(text):
        domain = match.group(1).lower()
        if (
            domain not in SAFE_EMAIL_DOMAINS
            and domain != "users.noreply.github.com"
            and not domain.endswith((".example", ".invalid", ".test"))
        ):
            issues.add("non-example-email")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history", action="store_true", help="also scan all reachable Git objects"
    )
    args = parser.parse_args()
    failures = set()
    names = set(
        git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    )
    for name in sorted(names - {""}):
        if sensitive_path(name):
            # A filename itself may contain an identity; do not print it.
            failures.add("working tree: forbidden local/private path")
            continue
        file = ROOT / name
        if file.is_symlink():
            failures.add("working tree: symlinks require explicit publication review")
        elif file.is_file():
            for issue in content_issues(file.read_bytes()):
                failures.add(f"working tree: {issue}")
    # Read the actual index blobs as well: editing a working file must not hide
    # a sensitive value which remains staged for the next commit.
    for record in git("ls-files", "--stage", "-z").decode().split("\0"):
        if not record:
            continue
        meta, name = record.split("\t", 1)
        _mode, oid, _stage = meta.split()
        for issue in content_issues(git("cat-file", "blob", oid)):
            failures.add(f"index: {issue}")
    for name in (
        ".env",
        "data/candidate-profile.local.json",
        "data/private-notes.local.md",
        "output/pdf/resume.pdf",
        ".DS_Store",
        "playwright-profile/session.json",
    ):
        if subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode:
            failures.add("required local path is not ignored")
    if args.history:
        for line in git("rev-list", "--objects", "--all").decode().splitlines():
            oid, _, name = line.partition(" ")
            kind = git("cat-file", "-t", oid).strip()
            if kind not in {b"blob", b"commit", b"tag"}:
                continue
            if name and sensitive_path(name):
                failures.add("history: forbidden local/private path")
            for issue in content_issues(git("cat-file", kind.decode(), oid)):
                failures.add(f"history: {issue}")
    if failures:
        print("Security check failed (matched values and filenames are hidden):", file=sys.stderr)
        for failure in sorted(failures):
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Security check passed: publishable files and index"
        + (" and full history." if args.history else ".")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
