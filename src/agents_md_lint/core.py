"""ネットワークを使わない、行単位のヒューリスティック検査。"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

RULES = {
    "C001": ("error", "必須・禁止の矛盾"),
    "C002": ("error", "パッケージマネージャ指定の矛盾"),
    "C003": ("error", "出力言語指定の矛盾"),
    "C004": ("error", "テストコマンド指定の矛盾"),
    "S001": ("warning", "参照パスが存在しない"),
    "S002": ("warning", "コマンドの定義が見つからない"),
    "S003": ("warning", "記載日付が古い"),
    "S004": ("warning", "非推奨語を使用している"),
    "D001": ("warning", "ロックファイルと指定が一致しない"),
    "D002": ("warning", "フレームワーク・言語の設定が見つからない"),
    "D003": ("warning", "構成表のディレクトリが存在しない"),
    "K001": ("error", "必須フロントマターがない"),
    "K002": ("warning", "スキル名とディレクトリ名が一致しない"),
    "K003": ("warning", "description の長さが範囲外"),
}
DEFAULT_EXCLUDES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".cache",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
MANAGERS = {
    "npm": "js",
    "pnpm": "js",
    "yarn": "js",
    "bun": "js",
    "pip": "py",
    "uv": "py",
    "poetry": "py",
}
LOCKS = {
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "Pipfile.lock": "pip",
}
COMMAND = re.compile(r"\b(npm run|pnpm(?: run)?|yarn(?: run)?|uv run|make|just)\s+([\w:.-]+)")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    file: str
    line: int
    message: str
    hint: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass
class Config:
    disabled_rules: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)
    deprecated_terms: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @classmethod
    def read(cls, path: Path) -> Config:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        allowed = {"disabled_rules", "severity", "deprecated_terms", "exclude"}
        if set(data) - allowed:
            raise ValueError("未知の設定項目があります")
        for key in ("disabled_rules", "deprecated_terms", "exclude"):
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError(f"{key} は文字列の配列で指定してください")
        severity = data.get("severity", {})
        if not isinstance(severity, dict) or any(
            v not in ("error", "warning") for v in severity.values()
        ):
            raise ValueError("severity は error または warning を指定してください")
        if (set(data.get("disabled_rules", [])) | set(severity)) - RULES.keys():
            raise ValueError("未知のルールIDがあります")
        return cls(**data)


@dataclass(frozen=True)
class Instruction:
    path: Path
    line: int
    kind: str
    subject: str
    value: str


def read_mapping(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise TypeError(f"設定ファイルはオブジェクトで指定してください: {path}")
    return data


def discover(root: Path, config: Config) -> list[Path]:
    def excluded(path: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        return any(
            fnmatch.fnmatch(relative, p) or fnmatch.fnmatch(relative + "/", p)
            for p in config.exclude
        )

    if root.is_file():
        return [root]
    files: list[Path] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in DEFAULT_EXCLUDES and not excluded(base / d))
        files.extend(
            base / n
            for n in sorted(names)
            if n in {"AGENTS.md", "CLAUDE.md", "SKILL.md"}
            and not excluded(base / n)
            and not (base / n).is_symlink()
        )
    return sorted(files)


def context_dir(path: Path, root: Path) -> Path:
    for directory in (path.parent, *path.parent.parents):
        if any(
            (directory / n).exists()
            for n in ("package.json", "pyproject.toml", "Makefile", "justfile")
        ):
            return directory
        if directory == root:
            break
    return root


def command_exists(base: Path, manager: str, target: str) -> bool:
    if manager.startswith(("npm", "pnpm", "yarn")):
        scripts = read_mapping(base / "package.json").get("scripts", {})
        return isinstance(scripts, dict) and target in scripts
    if manager == "uv run":
        data = read_mapping(base / "pyproject.toml")
        project = data.get("project", {})
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict) and target in scripts:
            return True
        # 外部ツールは依存宣言のパッケージ名との一致まで確認する。
        dependencies = project.get("dependencies", []) if isinstance(project, dict) else []
        groups = data.get("dependency-groups", {})
        if isinstance(groups, dict):
            dependencies = list(dependencies) + [
                v for group in groups.values() if isinstance(group, list) for v in group
            ]
        return (
            any(
                isinstance(dep, str) and re.split(r"[<>=!~\[ ;]", dep)[0] == target
                for dep in dependencies
            )
            or (base / target).is_file()
        )
    filename = "Makefile" if manager == "make" else "justfile"
    path = base / filename
    return path.exists() and bool(
        re.search(
            rf"^{re.escape(target)}(?:\s[^\n:]*)?\s*:(?!=)",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )


def extract(path: Path, number: int, line: str) -> list[Instruction]:
    result = []

    def add(kind: str, subject: str, value: str) -> None:
        result.append(Instruction(path, number, kind, subject, value))

    # コマンド例の言及と、明示的な指示を区別する。
    directive = bool(
        re.search(r"必ず|使用|使[うえ]|指定|実行|統一|always|must|use\b|run\b", line, re.IGNORECASE)
    )
    negative = bool(re.search(r"禁止|never|do not|must not", line, re.IGNORECASE))
    if directive and not negative:
        for manager, family in MANAGERS.items():
            if re.search(rf"(?<![A-Za-z0-9_-]){manager}(?![A-Za-z0-9_-])", line):
                add("manager", family, manager)
    language = re.search(r"日本語で|英語で|\bin (Japanese|English)\b", line, re.IGNORECASE)
    if language:
        subject_match = re.search(
            r"回答|コメント|ログ|ドキュメント|response|comments?|logs?|documentation",
            line,
            re.IGNORECASE,
        )
        subject = subject_match[0].lower() if subject_match else "出力"
        subject = {
            "response": "回答",
            "comment": "コメント",
            "comments": "コメント",
            "logs": "ログ",
            "log": "ログ",
            "documentation": "ドキュメント",
        }.get(subject, subject)
        add(
            "language",
            subject,
            "ja" if re.search(r"日本語|Japanese", language[0], re.IGNORECASE) else "en",
        )
    if re.search(r"テスト|\btest", line, re.IGNORECASE) and directive and not negative:
        for command in re.findall(r"`([^`]+)`", line):
            add("test", "テスト", command.strip())
    required = re.search(r"(?:必ず\s*|(?:always|must)\s+)(.+?)[。.!]?$", line, re.IGNORECASE)
    forbidden = re.search(r"(?:never|do not|must not)\s+(.+?)[。.!]?$", line, re.IGNORECASE)
    japanese = re.search(r"^\s*(?:[-*]\s*)?(.+?)\s*(?:は禁止|を禁止|禁止)[。.]?$", line)
    match = forbidden or japanese or required
    if match:
        subject = re.sub(r"[\s`。.!]+", "", match[1]).lower()
        subject = re.sub(r"(?:する|を実行)$", "", subject)
        add("polarity", subject, "禁止" if forbidden or japanese else "必須")
    return result


def lint(
    root: Path, config: Config | None = None, max_age_days: int = 365, today: date | None = None
) -> list[Finding]:
    config = config or Config()
    root = root.resolve()
    base_root = root.parent if root.is_file() else root
    today = today or date.today()
    findings: list[Finding] = []
    instructions: list[Instruction] = []
    contents: dict[Path, list[str]] = {}

    def emit(
        rule: str, path: Path, number: int, message: str, hint: str, severity: str | None = None
    ) -> None:
        lines = contents[path]
        if rule in config.disabled_rules:
            return
        if number > 1:
            suppression = re.search(
                r"<!--\s*agents-md-lint-disable-next-line\s+([A-Z0-9 ,]+)\s*-->", lines[number - 2]
            )
            if suppression and rule in re.split(r"[ ,]+", suppression[1].strip()):
                return
        findings.append(
            Finding(
                rule,
                config.severity.get(rule, severity or RULES[rule][0]),
                path.relative_to(base_root).as_posix(),
                number,
                message,
                hint,
            )
        )

    for path in discover(root, config):
        lines = path.read_text(encoding="utf-8").splitlines()
        contents[path] = lines
        base = context_dir(path, base_root)
        if path.name == "SKILL.md":
            metadata: dict[str, str] = {}
            end = (
                next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
                if lines and lines[0] == "---"
                else None
            )
            if end is not None:
                for index, line in enumerate(lines[1:end], 2):
                    match = re.match(r"^(name|description):\s*(.*?)\s*$", line)
                    if match:
                        value = match[2].strip("\"'")
                        if value in ("|", ">", "|-", ">-"):
                            following = lines[index:end]
                            value = " ".join(
                                s.strip() for s in following if s.startswith((" ", "\t"))
                            )
                        metadata[match[1]] = value
                        if match[1] == "name" and value != path.parent.name:
                            emit(
                                "K002",
                                path,
                                index,
                                f"name={value} とディレクトリ名が異なります",
                                "name をディレクトリ名に合わせてください",
                            )
                        if match[1] == "description" and not 10 <= len(value) <= 1024:
                            emit(
                                "K003",
                                path,
                                index,
                                "description は10〜1024文字が目安です",
                                "説明の長さを調整してください",
                            )
            for key in ("name", "description"):
                if not metadata.get(key):
                    emit(
                        "K001",
                        path,
                        1,
                        f"フロントマターに {key} が必要です",
                        "先頭の --- 内に文字列を記載してください",
                    )
        fenced = False
        tree_stack: list[tuple[int, str]] = []
        for number, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                fenced = not fenced
                tree_stack = []
                continue
            if "agents-md-lint-disable-next-line" in line:
                continue
            if not fenced:
                instructions.extend(extract(path, number, line))
            for token in config.deprecated_terms:
                if token.casefold() in line.casefold():
                    emit(
                        "S004",
                        path,
                        number,
                        f"非推奨語「{token}」があります",
                        "現在有効な表現に更新してください",
                    )
            for match in re.finditer(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b", line):
                try:
                    recorded = date(*map(int, match.groups()))
                except ValueError:
                    continue
                if (today - recorded).days > max_age_days:
                    emit(
                        "S003",
                        path,
                        number,
                        f"日付 {match[0]} が{max_age_days}日より古いです",
                        "内容を再確認して日付を更新してください",
                    )
            for match in COMMAND.finditer(line):
                if not command_exists(base, match[1], match[2]):
                    emit(
                        "S002",
                        path,
                        number,
                        f"{match[0]} の定義が見つかりません",
                        "スクリプト・依存宣言・ターゲットを確認してください",
                    )
            paths = re.findall(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)", line)
            paths += [
                s
                for s in re.findall(r"`([^`]+)`", line)
                if re.fullmatch(r"(?:\.{0,2}/)?[\w.@/-]+(?:\.[\w-]+|/)", s)
            ]
            for reference in dict.fromkeys(paths):
                if (
                    "://" in reference
                    or reference.startswith(("#", "/", "~"))
                    or any(c in reference for c in "*{}<>")
                ):
                    continue
                if not (path.parent / reference).exists() and not (base / reference).exists():
                    emit(
                        "S001",
                        path,
                        number,
                        f"参照先 {reference} が存在しません",
                        "指示書からの相対パスを修正するか参照先を用意してください",
                    )
            tree = re.match(r"^([ │]*)(?:├──|└──|\+--|\|--)\s+([\w.-]+)/", line)
            if tree:
                depth = len(tree[1])
                while tree_stack and tree_stack[-1][0] >= depth:
                    tree_stack.pop()
                relative = Path(*(name for _, name in tree_stack), tree[2])
                tree_stack.append((depth, tree[2]))
                if not (base / relative).is_dir():
                    emit(
                        "D003",
                        path,
                        number,
                        f"構成表の {relative} が存在しません",
                        "構成表を現在のディレクトリに合わせてください",
                    )
            for framework, markers in {
                "pytest": ("pyproject.toml", "pytest.ini", "setup.cfg"),
                "jest": ("package.json", "jest.config.js", "jest.config.ts"),
                "vitest": ("package.json", "vitest.config.ts", "vite.config.ts"),
                "TypeScript": ("tsconfig.json",),
                "Python": ("pyproject.toml", "setup.py", "requirements.txt"),
                "JavaScript": ("package.json",),
            }.items():
                if (
                    not fenced
                    and re.search(
                        rf"(?<![A-Za-z0-9_-]){framework}(?![A-Za-z0-9_-])", line, re.IGNORECASE
                    )
                    and re.search(r"使用|使う|use\b|must", line, re.IGNORECASE)
                ):
                    present = any(
                        (base / marker).exists()
                        and (
                            marker not in {"package.json", "pyproject.toml", "setup.cfg"}
                            or framework.lower()
                            in (base / marker).read_text(encoding="utf-8").lower()
                        )
                        for marker in markers
                    )
                    if not present:
                        emit(
                            "D002",
                            path,
                            number,
                            f"{framework} に対応する設定が見つかりません",
                            "設定ファイルまたは依存宣言を確認してください",
                        )
    for index, current in enumerate(instructions):
        if current.kind == "manager":
            base = context_dir(current.path, base_root)
            actual = {
                manager
                for lock, manager in LOCKS.items()
                if (base / lock).exists() and MANAGERS[manager] == current.subject
            }
            if actual and actual != {current.value}:
                emit(
                    "D001",
                    current.path,
                    current.line,
                    f"指定 {current.value} とロックファイル {', '.join(sorted(actual))} が一致しません",
                    "指定とロックファイルを統一してください",
                )
        for previous in instructions[:index]:
            if (current.kind, current.subject) != (
                previous.kind,
                previous.subject,
            ) or current.value == previous.value:
                continue
            # 別々の SKILL は独立した作業指示として扱う。
            if current.path != previous.path and "SKILL.md" in {
                current.path.name,
                previous.path.name,
            }:
                continue
            parent_child = current.path.parent != previous.path.parent and (
                current.path.parent in previous.path.parents
                or previous.path.parent in current.path.parents
            )
            if current.path.parent != previous.path.parent and not parent_child:
                continue
            rule = {"polarity": "C001", "manager": "C002", "language": "C003", "test": "C004"}[
                current.kind
            ]
            emit(
                rule,
                current.path,
                current.line,
                f"{previous.path.relative_to(base_root)}:{previous.line} の「{previous.value}」と「{current.value}」が衝突します",
                "適用対象を明示するか指示を統一してください",
                "warning" if parent_child else None,
            )
    return sorted(findings, key=lambda item: (item.file, item.line, item.rule_id, item.message))
