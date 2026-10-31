"""コマンドラインの入出力。"""

import argparse
import json
import sys
from pathlib import Path

from agents_md_lint.core import Config, lint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIエージェント向け指示書を静的検査します")
    parser.add_argument("path", nargs="?", default=".", help="検査対象のファイルまたはディレクトリ")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="出力形式")
    parser.add_argument("--max-age-days", type=int, default=365, help="日付の経過日数の上限")
    parser.add_argument("--config", type=Path, help="設定ファイルのパス")
    args = parser.parse_args(argv)
    try:
        root = Path(args.path)
        if not root.exists():
            raise ValueError(f"検査対象が存在しません: {root}")
        if args.max_age_days < 0:
            raise ValueError("--max-age-days は0以上で指定してください")
        config_path = (
            args.config or (root.parent if root.is_file() else root) / ".agents-md-lint.toml"
        )
        config = Config.read(config_path) if args.config or config_path.exists() else Config()
        findings = lint(root, config, args.max_age_days)
    except (OSError, ValueError, TypeError) as error:
        if args.format == "json":
            print(json.dumps({"error": f"検査を実行できません: {error}"}, ensure_ascii=False))
        else:
            print(f"検査を実行できません: {error}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps([finding.to_dict() for finding in findings], ensure_ascii=False, indent=2))
    elif findings:
        for finding in findings:
            label = "エラー" if finding.severity == "error" else "警告"
            print(
                f"{finding.file}:{finding.line}: {label} {finding.rule_id} {finding.message}\n  修正ヒント: {finding.hint}"
            )
        print(f"{len(findings)}件の指摘")
    else:
        print("指摘はありません")
    return int(any(finding.severity == "error" for finding in findings))
