# CLAUDE.md — CSDG (Cognitive-State Diary Generator)

## プロジェクト概要

体系的認知モデルに基づくAIキャラクター日記生成システム。
Actor-Critic型の敵対的検証ループにより、7日間のブログ日記を生成する。

- **リポジトリ:** https://github.com/mikotomiura/cognitive-State-Diary-generator
- **言語:** Python 3.11+
- **主要フレームワーク:** Pydantic, Anthropic API, Google Gemini API, matplotlib
- **アーキテクチャ:** 3-Phase Pipeline (State Update → Content Generation → Critic Evaluation)

---

## ドキュメント体系

作業を開始する前に、必ず以下のドキュメントを確認すること。

| ドキュメント | パス | 目的 |
|---|---|---|
| 機能設計書 | `docs/functional-design.md` | 機能要件・ユースケース・画面仕様 |
| 技術設計書 | `docs/architecture.md` | システム構成・データフロー・技術選定 |
| リポジトリ構造定義書 | `docs/repository-structure.md` | ディレクトリ構成・ファイル配置規約 |
| 開発ガイドライン | `docs/development-guidelines.md` | コーディング規約・Git運用・テスト方針 |
| ユビキタス言語定義 | `docs/glossary.md` | プロジェクト固有の用語定義 |
| ERRE 設計文書 | `docs/erre-design.md` | ERRE フレームワークと CSDG の対応関係 |
| MVP 実装ワークフロー | `docs/mvp-implementation-workflow.md` | フェーズ別の実装手順・プロンプト |

---

## 開発の原則

1. **設計書ファーストで実装する。** コードを書く前にドキュメントを読み、設計意図を理解する。
2. **型安全性を最優先する。** Pydanticモデルによる厳密な型定義を遵守する。
3. **テストなしのコミットは禁止。** 新機能・バグ修正には必ずテストを伴う。
4. **プロンプトはコードに埋め込まない。** `prompts/` ディレクトリの外部Markdownファイルで管理する。
5. **Self-Healingを前提とする。** LLM出力のパースエラーは必ず発生するものとしてフォールバックを実装する。

---

## よく使うコマンド

```bash
uv sync                        # 依存関係のインストール
pytest tests/ -v               # テストの実行
mypy csdg/ --strict            # 型チェック
ruff check csdg/               # リンター
ruff format csdg/              # フォーマッター
python -m csdg.main            # パイプラインの実行
python -m csdg.main --day 4    # 特定のDayのみ実行
```

---

## コードベースの重要な規約

`schemas.py` 変更手順・プロンプト変更手順・感情パラメータ範囲等の詳細は `docs/development-guidelines.md` を参照すること。

---

## .steering — 構造化作業ノート

各作業セッションでは、`.steering/` フォルダに作業記録を残すこと。
ディレクトリ構造は `[YYYYMMDD]-[タスク名]/` 単位で作成する。

### ディレクトリ構造

```
.steering/
└── [YYYYMMDD]-[タスク名]/
    ├── requirement.md    # 今回の作業の実装内容・要件
    ├── design.md         # 実装アプローチと変更内容
    ├── tasklist.md       # 具体的な実装タスク（チェックリスト形式）
    ├── blockers.md       # (オプション) ブロッカーの記録
    └── decisions.md      # (オプション) 重要な決定事項の記録
```

### 作業開始時のフロー

1. `.steering/[YYYYMMDD]-[タスク名]/` ディレクトリを作成する
2. `requirement.md` に要件を記述する
3. `design.md` に実装アプローチを記述する
4. `tasklist.md` にタスクを分解する
5. 実装を進めながら、各ファイルを随時更新する
6. ブロッカーや重要な決定が発生した場合は `blockers.md` / `decisions.md` に記録する

---

## サブエージェント

`.claude/agents/` 配下のサブエージェント定義を参照すること。
サブエージェントは詳細な作業を実行した後、結果を簡潔なレポートとして親エージェントに返す。

| カテゴリ | エージェント | 用途 |
|---|---|---|
| レビュー | `code-reviewer` | コードレビュー |
| レビュー | `test-analyzer` | テスト結果の分析 |
| レビュー | `security-checker` | セキュリティチェック |
| 情報収集 | `impact-analyzer` | 変更の影響範囲調査 |
| 情報収集 | `dependency-checker` | 依存関係の確認 |
| 情報収集 | `file-finder` | 関連ファイルの検索 |
| 実行 | `test-runner` | テストの実行 |
| 実行 | `build-executor` | ビルドの実行 |
| 実行 | `log-analyzer` | ログファイルの分析 |

---

## スラッシュコマンド

`.claude/commands/` 配下のコマンド定義を参照すること。

| コマンド | 用途 |
|---|---|
| `/start-task` | タスク開始・作業記録初期化 |
| `/implement feat\|fix\|refactor` | 新機能追加 / バグ修正 / リファクタリング |
| `/review-changes` | コミット前レビュー（動的 git 取得 + 並列実行） |
| `/finish-task` | タスク完了処理（テスト・コミット） |
| `/run-tests` | テスト実行・分析ワークフロー |
| `/update-docs` | ドキュメント更新ワークフロー |
| `/add-scenario` | シナリオ(DailyEvent)追加ワークフロー |
| `/tune-prompt` | プロンプトチューニングワークフロー |

---

## スキル

`.claude/skills/` 配下のスキル定義を参照すること。

| スキル | 用途 |
|---|---|
| `python-standards` | Pythonコーディング規約・ベストプラクティス |
| `pydantic-patterns` | Pydanticモデル設計パターン |
| `prompt-engineering` | LLMプロンプト設計の原則 |
| `test-standards` | テスト設計・実装の基準 |

---

## 禁止事項

- `schemas.py` のモデルを変更する際、既存のテストを壊すような破壊的変更を無断で行わないこと
- プロンプトファイルにPythonコードを直接埋め込まないこと
- `config.py` の感情感度係数 (`EMOTION_SENSITIVITY`) を根拠なく変更しないこと
- キャラクター設定（ペルソナ）の禁則事項を無視した日記を生成しないこと
- `.steering/` の作業記録を省略しないこと
