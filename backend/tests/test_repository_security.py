from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_private_local_files_are_ignored_by_repository_policy() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for required_rule in (
        ".env",
        "data/*",
        "*.local.md",
        "*.private.md",
        "*.db",
        "*.sqlite",
        "playwright-profile/",
    ):
        assert required_rule in gitignore


def test_public_environment_example_keeps_external_services_opt_in() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "AI_ALLOW_REMOTE=false" in example
    assert "SLACK_NOTIFY_ENABLED=false" in example
    assert "SLACK_WEBHOOK_URL=\n" in example
    assert "SLACK_BOT_TOKEN=\n" in example
    assert "SARAMIN_API_KEY=\n" in example


def test_compose_exposes_only_loopback_app_ports_and_no_database_port() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    db_section, backend_section = compose.split("  backend:", maxsplit=1)

    assert "ports:" not in db_section
    assert '"127.0.0.1:${BACKEND_PORT:-8000}:8000"' in backend_section
    assert '"127.0.0.1:${FRONTEND_PORT:-41739}:5173"' in backend_section
    assert "  scheduler:" in compose


def test_release_scanner_rejects_private_paths_and_real_contact_patterns() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "security_check", ROOT / "scripts/security_check.py"
    )
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    for path in (
        ".env",
        "data/candidate-profile.local.json",
        "output/pdf/resume.pdf",
        ".DS_Store",
        "frontend/.env.production",
        "playwright/.auth/state.json",
        "secrets/api.json",
    ):
        assert scanner.sensitive_path(path)
    assert not scanner.sensitive_path(".env.example")
    assert not scanner.sensitive_path("backend/examples/candidate-profile.example.json")
    assert not scanner.sensitive_path("data/README.md")
    assert scanner.content_issues(("person" + "@mail.nonexample").encode()) == {"non-example-email"}
    assert scanner.content_issues(("010" + "-1234-5678").encode()) == {"phone-number"}
    assert not scanner.content_issues(b"sample@example.com")
    assert not scanner.content_issues(b"maintainer@users.noreply.github.com")
    assert scanner.content_issues(("/" + "Users" + "/fixture/project").encode()) == {
        "personal-filesystem-path"
    }


def test_release_scanner_reads_staged_and_historical_bytes(tmp_path, monkeypatch, capsys) -> None:
    import importlib.util
    import subprocess

    spec = importlib.util.spec_from_file_location(
        "security_check", ROOT / "scripts/security_check.py"
    )
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["security_check.py"])

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Example", "-c", "user.email=dev@example.org", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-b", "main")
    (tmp_path / ".gitignore").write_text(".env\ndata/*\noutput/\n.DS_Store\nplaywright-profile/\n")
    secret = "sk-" + "syntheticnotarealcredential123456789"
    target = tmp_path / "config.txt"
    target.write_text(secret)
    git("add", ".gitignore", "config.txt")
    target.write_text("safe working copy")
    assert scanner.main() == 1  # The index still contains the old value.
    assert secret not in capsys.readouterr().err
    git("commit", "-m", "Synthetic regression fixture")
    git("add", "config.txt")
    git("commit", "-m", "Clear current value")
    assert scanner.main() == 0
    monkeypatch.setattr("sys.argv", ["security_check.py", "--history"])
    assert scanner.main() == 1  # Only history contains the value now.
    assert secret not in capsys.readouterr().err
