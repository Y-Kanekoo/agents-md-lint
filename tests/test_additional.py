"""日本語表記と配布用エントリポイントの追加検査。"""

import json
import runpy
from pathlib import Path

import pytest

from agents_md_lint.cli import main
from agents_md_lint.core import Config, lint


def test_japanese_without_spaces(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "必ずpushする\npush禁止\nnpmを使用\npnpmを使用\nPythonを使用\nJavaScriptを使用\n",
        encoding="utf-8",
    )
    findings = lint(tmp_path)
    assert {"C001", "C002", "D002"} <= {finding.rule_id for finding in findings}
    assert sum(finding.rule_id == "D002" for finding in findings) == 2


def test_module_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agents-md-lint"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("agents_md_lint", run_name="__main__")
    assert result.value.code == 0


def test_default_config_and_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "AGENTS.md").write_text("`missing.md`\n", encoding="utf-8")
    (tmp_path / ".agents-md-lint.toml").write_text('[severity]\nS001="error"', encoding="utf-8")
    assert main([str(tmp_path), "--format", "json"]) == 1
    finding = json.loads(capsys.readouterr().out)[0]
    assert set(finding) == {"rule_id", "severity", "file", "line", "message", "hint"}


def test_no_false_conflict_between_language_subjects(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("回答は日本語で\nコメントは英語で\n", encoding="utf-8")
    assert not lint(tmp_path)


def test_severity_override_on_nested_conflict(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use uv\n", encoding="utf-8")
    (tmp_path / "child").mkdir()
    (tmp_path / "child/AGENTS.md").write_text("Use poetry\n", encoding="utf-8")
    findings = lint(tmp_path, Config(severity={"C002": "error"}))
    assert len(findings) == 1 and findings[0].severity == "error"
