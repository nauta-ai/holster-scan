from pathlib import Path

from holster_scan.cli import main


def test_cli_high_finding_exit_code(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("import reqeusts\n")

    code = main(["scan", str(tmp_path), "--offline"])
    out = capsys.readouterr().out

    assert code == 1
    assert "reqeusts" in out


def test_cli_direct_path_form(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("import reqeusts\n")

    code = main([str(tmp_path), "--offline"])
    out = capsys.readouterr().out

    assert code == 1
    assert "reqeusts" in out


def test_cli_clean_project_exit_code(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("import requests\n")
    (tmp_path / "requirements.txt").write_text("requests\n")

    code = main(["scan", str(tmp_path), "--offline"])
    out = capsys.readouterr().out

    assert code == 0
    assert "No findings" in out


def test_config_allowlist_suppresses_named_package(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("import reqeusts\n")
    (tmp_path / ".holster.yml").write_text("allow:\n  - reqeusts\nfail_on: high\n")

    code = main(["scan", str(tmp_path), "--offline", "--format", "json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"finding_count": 0' in out


def test_javascript_scan_does_not_crash(tmp_path: Path, capsys):
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"latest"}}')
    (tmp_path / "index.ts").write_text("import React from 'react';\nconst x = require('reqeusts');\n")

    code = main(["scan", str(tmp_path), "--offline", "--format", "json"])
    out = capsys.readouterr().out

    assert code == 1
    assert "reqeusts" in out
