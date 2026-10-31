"""一時ディレクトリだけで検査する回帰テスト。"""

import json
from datetime import date
from pathlib import Path

import pytest

from agents_md_lint.cli import main
from agents_md_lint.core import Config, command_exists, discover, lint


def write(root: Path, name: str, content: str = "") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def ids(root: Path, config: Config | None = None) -> set[str]:
    return {finding.rule_id for finding in lint(root, config, today=date(2026, 1, 1))}


def test_contradictions(tmp_path: Path) -> None:
    write(
        tmp_path,
        "AGENTS.md",
        "must deploy\nnever deploy\n必ず push\npush 禁止\nUse npm\nUse pnpm\n回答は日本語で\n回答は英語で\nテストは `npm run test` を実行\nテストは `npm run check` を実行\n",
    )
    write(tmp_path, "package.json", '{"scripts":{"test":"ok","check":"ok"}}')
    assert {"C001", "C002", "C003", "C004"} <= ids(tmp_path)
    assert all(f.severity == "error" for f in lint(tmp_path) if f.rule_id.startswith("C"))


def test_scopes(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "Use npm\n")
    write(tmp_path, "child/AGENTS.md", "Use pnpm\n")
    write(tmp_path, "sibling/AGENTS.md", "Use pnpm\n")
    write(
        tmp_path,
        "skills/a/SKILL.md",
        "---\nname: a\ndescription: 十分な文字数の説明を書きます\n---\nUse yarn\n",
    )
    conflicts = [f for f in lint(tmp_path) if f.rule_id == "C002"]
    assert len(conflicts) == 2
    assert all(f.severity == "warning" for f in conflicts)


def test_same_directory_and_english_language(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "Respond in Japanese\n")
    write(tmp_path, "CLAUDE.md", "Respond in English\n")
    assert "C003" in ids(tmp_path)


def test_stale_paths_dates_terms(tmp_path: Path) -> None:
    write(
        tmp_path,
        "AGENTS.md",
        "[資料](missing.md) `absent/` `exists.md` [外部](https://example.com) [章](#ok)\n2020-01-01\t2020/02/01\t2020-99-99\t2099-01-01\nOldModel\n",
    )
    write(tmp_path, "exists.md")
    findings = lint(tmp_path, Config(deprecated_terms=["oldmodel"]), today=date(2026, 1, 1))
    assert sum(f.rule_id == "S001" for f in findings) == 2
    assert sum(f.rule_id == "S003" for f in findings) == 2
    assert sum(f.rule_id == "S004" for f in findings) == 1


@pytest.mark.parametrize("manager", ["npm run", "pnpm", "pnpm run", "yarn", "yarn run"])
def test_js_commands(tmp_path: Path, manager: str) -> None:
    write(tmp_path, "package.json", '{"scripts":{"test":"ok"}}')
    write(tmp_path, "AGENTS.md", f"`{manager} test`\n`{manager} missing`\n")
    assert [f.line for f in lint(tmp_path) if f.rule_id == "S002"] == [2]


def test_uv_make_just_commands(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\ndependencies=["pytest>=8"]\n[project.scripts]\napp="a:b"\n[dependency-groups]\ndev=["ruff>=0.9", {include-group="other"}]\n',
    )
    write(tmp_path, "Makefile", "test: build\n\techo ok\n")
    write(tmp_path, "justfile", "check arg:\n    echo ok\n")
    write(tmp_path, "tool.py")
    for manager, target in [
        ("uv run", "pytest"),
        ("uv run", "ruff"),
        ("uv run", "app"),
        ("uv run", "tool.py"),
        ("make", "test"),
        ("just", "check"),
    ]:
        assert command_exists(tmp_path, manager, target)
        assert not command_exists(tmp_path, manager, "missing")
    write(tmp_path, "AGENTS.md", "`uv run absent`\n`make absent`\n`just absent`\n")
    assert sum(f.rule_id == "S002" for f in lint(tmp_path)) == 3


def test_actual_configuration(tmp_path: Path) -> None:
    write(
        tmp_path,
        "AGENTS.md",
        "Use npm\npytest を使用\njest を使用\nvitest を使用\nTypeScript を使用\n```text\n├── src/\n│   └── absent/\n└── missing/\n```\n",
    )
    write(tmp_path, "pnpm-lock.yaml")
    write(tmp_path, "src/ok.py")
    findings = lint(tmp_path)
    assert {"D001", "D002", "D003"} <= {f.rule_id for f in findings}
    assert sum(f.rule_id == "D002" for f in findings) == 4
    assert sum(f.rule_id == "D003" for f in findings) == 2
    write(tmp_path, "pyproject.toml", '[project]\ndependencies=["pytest"]')
    write(tmp_path, "package.json", '{"devDependencies":{"jest":"1","vitest":"1"}}')
    write(tmp_path, "tsconfig.json", "{}")
    assert "D002" not in ids(tmp_path)


def test_skills(tmp_path: Path) -> None:
    write(tmp_path, "a/SKILL.md", "説明のみ")
    write(tmp_path, "b/SKILL.md", "---\nname: other\ndescription: 短い\n---\n[補助](helper.py)\n")
    write(tmp_path, "c/SKILL.md", "---\nname: c\ndescription: |\n  十分な長さを持つ説明です\n---\n")
    findings = lint(tmp_path)
    assert sum(f.rule_id == "K001" for f in findings) == 2
    assert {"K002", "K003", "S001"} <= ids(tmp_path)
    assert not [f for f in findings if f.file == "c/SKILL.md"]


def test_discovery_exclusions_file_and_symlink(tmp_path: Path) -> None:
    for name in [
        "AGENTS.md",
        "CLAUDE.md",
        "a/SKILL.md",
        "node_modules/AGENTS.md",
        ".git/AGENTS.md",
        "ignored/AGENTS.md",
    ]:
        write(tmp_path, name)
    (tmp_path / "link").symlink_to(tmp_path / "a", target_is_directory=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "b/AGENTS.md").symlink_to(tmp_path / "AGENTS.md")
    assert len(discover(tmp_path, Config(exclude=["ignored/"]))) == 3
    assert discover(tmp_path / "AGENTS.md", Config()) == [tmp_path / "AGENTS.md"]
    assert not lint(tmp_path / "AGENTS.md")


def test_suppression_config(tmp_path: Path) -> None:
    write(
        tmp_path,
        "AGENTS.md",
        "<!-- agents-md-lint-disable-next-line S001, S004 -->\n`absent.md` obsolete\n`other.md`\n",
    )
    config_path = write(
        tmp_path,
        ".agents-md-lint.toml",
        'deprecated_terms=["obsolete"]\n[severity]\nS001="error"\n',
    )
    findings = lint(tmp_path, Config.read(config_path))
    assert len(findings) == 1 and findings[0].line == 3
    assert findings[0].severity == "error"
    assert not lint(tmp_path, Config(disabled_rules=["S001"]))


@pytest.mark.parametrize(
    "content",
    [
        "unknown=[]",
        'exclude="oops"',
        "exclude=[1]",
        '[severity]\nS001="info"',
        'disabled_rules=["BAD"]',
        "severity=[]",
    ],
)
def test_bad_config(tmp_path: Path, content: str) -> None:
    path = write(tmp_path, "config.toml", content)
    with pytest.raises(ValueError):
        Config.read(path)


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "AGENTS.md", "must deploy\nnever deploy\n")
    assert main([str(tmp_path)]) == 1
    assert "エラー C001" in capsys.readouterr().out
    assert main([str(tmp_path), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data[0]["rule_id"] == "C001" and data[0]["hint"]
    write(tmp_path, "AGENTS.md", "`absent.md`\n")
    assert main([str(tmp_path)]) == 0
    assert "警告 S001" in capsys.readouterr().out
    write(tmp_path, "AGENTS.md", "")
    assert main([str(tmp_path / "AGENTS.md")]) == 0
    assert "指摘はありません" in capsys.readouterr().out
    assert main([str(tmp_path), "--max-age-days", "-1"]) == 2
    assert "0以上" in capsys.readouterr().err
    assert main([str(tmp_path / "missing"), "--format", "json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert main([str(tmp_path), "--config", str(tmp_path / "missing.toml")]) == 2
    assert "実行できません" in capsys.readouterr().err


def test_invalid_repository_metadata(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "`npm run test`\n")
    write(tmp_path, "package.json", "[]")
    assert main([str(tmp_path)]) == 2


def test_fenced_examples_do_not_conflict(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "Use npm\n```text\nUse pnpm\n```\n")
    assert "C002" not in ids(tmp_path)
