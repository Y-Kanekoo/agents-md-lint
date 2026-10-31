# agents-md-lint

AIエージェント向け指示書の矛盾・陳腐化・リポジトリ実態とのずれを、ネットワークやLLMなしで検査する小さな試作です。

A small, offline, heuristic linter for AGENTS.md, CLAUDE.md and SKILL.md. It checks conflicting instructions, stale references and repository drift. Python 3.11+; no runtime dependencies.

## インストール

Python 3.11以上と uv が必要です。

```sh
uv tool install git+https://github.com/Y-Kanekoo/agents-md-lint
```

ソースから実行する場合:

```sh
uv sync --locked
uv run agents-md-lint .
```

## 使い方

```sh
agents-md-lint [PATH] [--format text|json] [--max-age-days N] [--config .agents-md-lint.toml]
agents-md-lint ./my-repo --format json --max-age-days 180
agents-md-lint ./my-repo/AGENTS.md
```

PATH の既定値はカレントディレクトリです。ディレクトリ内の AGENTS.md、CLAUDE.md、SKILL.md を再帰的に探索します。`.git`、`node_modules`、`.venv`、`venv`、`__pycache__`、`.cache`、ビルド出力・検査キャッシュを除外し、探索中のシンボリックリンクは辿りません。ファイルを直接指定すると、そのファイルだけを検査します。

終了コードは **0: errorなし（warningのみを含む）／1: errorあり／2: 引数・設定・読み取りエラー**。指示書に記載されたコマンドを実行することはありません。

テキスト出力は日本語です。JSON は指摘の配列で、各要素に `rule_id`、`severity`、`file`（検査対象からの相対パス）、`line`（1始まり）、`message`、`hint` を持ちます。実行エラー時のJSONは `{"error": "説明"}` です。

## ルール

| ID | 既定のseverity | 検査 |
| --- | --- | --- |
| C001 | error | 同じ操作への「必ず／always／must」と「禁止／never／do not」の衝突 |
| C002 | error | npm/pnpm/yarn/bun または pip/uv/poetry の指定の衝突 |
| C003 | error | 同じ対象の「日本語で／英語で／in Japanese／in English」の衝突 |
| C004 | error | テスト指示に記載されたバッククォート内のコマンドの衝突 |
| S001 | warning | Markdownリンクとバッククォート内のファイル・ディレクトリ参照の欠落 |
| S002 | warning | npm run、pnpm、yarn、uv run、make、just の実行対象の定義欠落 |
| S003 | warning | YYYY-MM-DD／YYYY/MM/DD が経過日数の上限を超過（既定365日） |
| S004 | warning | 設定した非推奨語への一致（大文字・小文字を区別しない部分一致） |
| D001 | warning | パッケージマネージャと同じ言語系のロックファイルの不一致 |
| D002 | warning | pytest/jest/vitest、Python/JavaScript/TypeScript の設定・依存宣言欠落 |
| D003 | warning | ツリー表記のディレクトリの欠落 |
| K001 | error | SKILL.md の先頭フロントマターに name/description がない、または空 |
| K002 | warning | name と SKILL.md を置くディレクトリ名が異なる |
| K003 | warning | description が10〜1024文字の範囲外 |

同一ファイルと同一ディレクトリの指示書を比較します。祖先・子孫ディレクトリの指示は上書きを想定して、衝突を **warning** にします。兄弟ディレクトリは比較せず、別ファイルの SKILL.md は独立した指示として扱います。設定によるseverity変更を最後に適用します。

参照パスは指示書のディレクトリ、次に最寄りのプロジェクト設定のディレクトリを基準に確認します。コマンド・ロックファイルは、検査対象内で最も近い package.json／pyproject.toml／Makefile／justfile のあるディレクトリを使います。単一ファイル指定の場合は親ディレクトリが検査の境界です。

## 設定

検査対象のルート（単一ファイルの場合はその親）にある `.agents-md-lint.toml` を自動読込します。`--config` の相対パスは実行時のカレントディレクトリ基準です。未知のキー・ルールIDや不正な型は実行エラーになります。

```toml
disabled_rules = ["S003"]
deprecated_terms = ["old-example-model", "旧手順"]
exclude = ["vendor/**", "fixtures/**"]

[severity]
S001 = "error"
C004 = "warning"
```

除外はルートからの相対POSIXパスへのglobです。リポジトリ自身の設定では、意図的に問題を含むデモを一括検査から除外しています。デモを直接指定するとデモ側の設定が使われます。

直後の1行について、ルールを抑制できます（複数IDは空白またはカンマ区切り）。

```markdown
<!-- agents-md-lint-disable-next-line S001 -->
参照: `planned.md`
```

## デモ

```sh
./scripts/demo.sh
```

問題のある例の終了コード1を確認してから、問題のない例を実行します。以下は実際の出力です。

```text
=== 問題を含む例 ===
AGENTS.md:2: 警告 D001 指定 npm とロックファイル pnpm が一致しません
  修正ヒント: 指定とロックファイルを統一してください
AGENTS.md:3: エラー C002 AGENTS.md:2 の「npm」と「pnpm」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:5: エラー C001 AGENTS.md:4 の「必須」と「禁止」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:7: エラー C003 AGENTS.md:6 の「ja」と「en」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:8: エラー C002 AGENTS.md:3 の「pnpm」と「npm」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:8: 警告 D001 指定 npm とロックファイル pnpm が一致しません
  修正ヒント: 指定とロックファイルを統一してください
AGENTS.md:9: エラー C002 AGENTS.md:3 の「pnpm」と「npm」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:9: エラー C004 AGENTS.md:8 の「npm run test」と「npm run verify」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
AGENTS.md:9: 警告 D001 指定 npm とロックファイル pnpm が一致しません
  修正ヒント: 指定とロックファイルを統一してください
AGENTS.md:9: 警告 S002 npm run verify の定義が見つかりません
  修正ヒント: スクリプト・依存宣言・ターゲットを確認してください
AGENTS.md:10: 警告 S001 参照先 docs/missing.md が存在しません
  修正ヒント: 指示書からの相対パスを修正するか参照先を用意してください
AGENTS.md:11: 警告 S003 日付 2020-01-01 が365日より古いです
  修正ヒント: 内容を再確認して日付を更新してください
AGENTS.md:12: 警告 S004 非推奨語「old-example-model」があります
  修正ヒント: 現在有効な表現に更新してください
AGENTS.md:13: 警告 D002 pytest に対応する設定が見つかりません
  修正ヒント: 設定ファイルまたは依存宣言を確認してください
AGENTS.md:15: 警告 D003 構成表の src が存在しません
  修正ヒント: 構成表を現在のディレクトリに合わせてください
AGENTS.md:16: 警告 D003 構成表の obsolete が存在しません
  修正ヒント: 構成表を現在のディレクトリに合わせてください
child/AGENTS.md:2: 警告 C002 AGENTS.md:2 の「npm」と「yarn」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
child/AGENTS.md:2: 警告 C002 AGENTS.md:3 の「pnpm」と「yarn」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
child/AGENTS.md:2: 警告 C002 AGENTS.md:8 の「npm」と「yarn」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
child/AGENTS.md:2: 警告 C002 AGENTS.md:9 の「npm」と「yarn」が衝突します
  修正ヒント: 適用対象を明示するか指示を統一してください
child/AGENTS.md:2: 警告 D001 指定 yarn とロックファイル pnpm が一致しません
  修正ヒント: 指定とロックファイルを統一してください
skills/broken/SKILL.md:2: 警告 K002 name=mismatch とディレクトリ名が異なります
  修正ヒント: name をディレクトリ名に合わせてください
skills/broken/SKILL.md:3: 警告 K003 description は10〜1024文字が目安です
  修正ヒント: 説明の長さを調整してください
skills/broken/SKILL.md:5: 警告 S001 参照先 helper.py が存在しません
  修正ヒント: 指示書からの相対パスを修正するか参照先を用意してください
24件の指摘
=== 問題のない例 ===
指摘はありません
```

## 開発・検証

```sh
uv sync --locked
./scripts/check.sh
uv run agents-md-lint .
```

check.sh は ruff check、ruff format --check、mypy --strict（src）、pytest を順に実行します。pytest は tmp_path で検査用リポジトリを作成し、ネットワークや外部サービスを使いません。カバレッジ85%未満では失敗します。スクリプトは uv のキャッシュをリポジトリ内の `.cache/uv` に置きます。初回の開発依存インストールにはネットワークが必要です。

## 制限

- 自然言語の意味解析ではなくヒューリスティックです。誤検出・見逃しがあり、指摘は人間が確認してください。日本語・英語の代表的な表現を対象とし、条件分岐、引用、言い換え、複雑な否定は解釈しません。
- 必須／禁止は操作文字列を簡易正規化して比較します。言語指定は回答・コメント・ログ・ドキュメント等の最初に現れる対象を比較し、対象省略時は「出力」として扱います。コードフェンス内は矛盾・言語設定の検査から除外します。
- 複数のテストコマンドが意図的な工程でもC004の候補になります。用途の違いを自動推定しません。抑制・設定で調整してください。
- コマンド検査は package.json のscripts、pyproject.toml の project.scripts・依存宣言・dependency-groups、ローカルスクリプト、Makefile/justfile の単純なターゲットを対象にします。実行可能ファイル名とパッケージ名の違い、グループ参照、グローバルコマンド、組み込みサブコマンドは解決しません。
- 設定ファイルの存在・依存名を手掛かりに検査します。ロックファイルが全くない場合や、未対応の言語・フレームワークは不一致と断定しません。バージョンの整合性は検査しません。
- パスはMarkdownリンクと、拡張子または末尾スラッシュがある単純なバッククォート表記を対象とします。URL・アンカー・絶対パス・ホーム相対パス・テンプレート表記は検査しません。
- 構成表は `├── name/`、`└── name/`、`+-- name/`、`|-- name/` の表記とインデントを対象にします。プロジェクト設定のディレクトリ基準で、記載されたディレクトリの存在だけを確認します。
- YAMLは依存を増やさず、先頭の `---` で囲まれた name/description の単純な文字列・引用文字列・インデント付きブロック文字列を読みます。完全なYAML構文検証、アンカーや複雑な値は未対応です。descriptionの長さはUnicode文字数です。
- 日付の意味や実際の更新日は推定しません。既定の非推奨語リストは空です。提供終了モデル等の名称は利用者が設定してください。
