# リポジトリ構造定義書 (Repository Structure)

> **目的:** CSDG プロジェクトのディレクトリ構成、各ファイルの配置規約、命名規則、および新規ファイル追加時のルールを定義する。
> 「何を作るか」は `functional-design.md` に、「なぜそう設計するか」は `architecture.md` に委譲する。
> 本ドキュメントは「どこに何を置くか」を記述する。

---

## 1. ディレクトリツリー全体図

```
cognitive-State-Diary-generator/
│
├── CLAUDE.md                          # Claude Code マスター指示書
├── README.md                          # プロジェクト概要・セットアップ手順・実行方法
├── pyproject.toml                     # プロジェクト定義・依存関係・ツール設定
├── uv.lock                            # 依存関係のロックファイル (自動生成)
├── .env.example                       # 環境変数のテンプレート
├── .gitignore                         # Git除外ルール
├── .python-version                    # Python バージョン指定
│
├── docs/                              # 永続的ドキュメント群
│   ├── functional-design.md           #   機能設計書
│   ├── architecture.md                #   技術設計書
│   ├── repository-structure.md        #   本ドキュメント
│   ├── development-guidelines.md      #   開発ガイドライン
│   └── glossary.md                    #   ユビキタス言語定義
│
├── csdg/                              # メインアプリケーションパッケージ
│   ├── __init__.py                    #   パッケージ初期化 (バージョン定義)
│   ├── main.py                        #   エントリポイント (CLI)
│   ├── config.py                      #   設定管理 (pydantic-settings)
│   ├── schemas.py                     #   Pydantic モデル定義
│   ├── scenario.py                    #   7日分のシナリオ定義
│   ├── visualization.py              #   状態推移グラフ生成
│   │
│   └── engine/                        #   パイプラインエンジン
│       ├── __init__.py
│       ├── actor.py                   #     Actor (Phase 1 + Phase 2)
│       ├── critic.py                  #     Critic (Phase 3, 3層構造: RuleBased/Statistical/LLMJudge)
│       ├── pipeline.py               #     パイプライン制御 (ループ・リトライ)
│       ├── llm_client.py             #     LLM API 抽象化レイヤー
│       ├── state_transition.py       #     状態遷移の半数式化 (決定論的骨格+LLM delta+max_llm_delta制約)
│       ├── memory.py                 #     2層メモリ構造 (ShortTerm + LongTerm)
│       └── critic_log.py             #     Criticログ蓄積・軽量フィードバック (JSON Lines永続化)
│
├── prompts/                           # プロンプトモジュール (外部Markdownファイル)
│   ├── System_Persona.md             #   キャラクターの不変ルール (意味記憶)
│   ├── Prompt_StateUpdate.md         #   Phase 1: 状態遷移ルール
│   ├── Prompt_Generator.md           #   Phase 2: 日記生成ルール
│   └── Prompt_Critic.md              #   Phase 3: 評価基準・採点基準
│
├── tests/                             # テストコード
│   ├── __init__.py
│   ├── conftest.py                    #   共通フィクスチャ定義
│   ├── test_schemas.py               #   Pydantic モデルのバリデーションテスト
│   ├── test_scenario.py              #   シナリオ定義のバリデーションテスト
│   ├── test_actor.py                 #   Actor の単体テスト
│   ├── test_critic.py                #   Critic の単体テスト
│   ├── test_pipeline.py              #   パイプラインの統合テスト
│   ├── test_config.py                #   設定管理のテスト
│   ├── test_visualization.py         #   可視化のテスト
│   ├── test_state_transition.py     #   状態遷移の半数式化テスト (max_llm_delta含む)
│   ├── test_memory.py               #   2層メモリ構造テスト
│   ├── test_critic_log.py           #   Criticログ蓄積テスト
│   └── fixtures/                      #   テスト用固定データ
│       ├── sample_state.json          #     サンプル CharacterState
│       ├── sample_event.json          #     サンプル DailyEvent
│       ├── sample_critic_score.json   #     サンプル CriticScore
│       └── sample_diary.md            #     サンプル日記テキスト
│
├── output/                            # パイプライン出力 (Git管理外)
│   ├── day_01.md 〜 day_07.md         #   生成された日記ファイル
│   ├── generation_log.json            #   実行ログ
│   └── state_trajectory.png           #   状態推移グラフ
│
├── .steering/                         # 構造化作業ノート
│   └── [YYYYMMDD]-[タスク名]/
│       ├── requirement.md             #     要件定義
│       ├── design.md                  #     実装アプローチ
│       ├── tasklist.md                #     タスクリスト
│       ├── blockers.md                #     (オプション) ブロッカー記録
│       └── decisions.md               #     (オプション) 決定事項記録
│
└── .claude/                           # Claude Code 拡張設定
    ├── agents/                        #   サブエージェント定義
    │   ├── code-reviewer.md           #     コードレビュー
    │   ├── test-analyzer.md           #     テスト結果分析
    │   ├── security-checker.md        #     セキュリティチェック
    │   ├── impact-analyzer.md         #     影響範囲分析
    │   ├── dependency-checker.md      #     依存関係確認
    │   ├── file-finder.md             #     関連ファイル検索
    │   ├── test-runner.md             #     テスト実行
    │   ├── build-executor.md          #     ビルド実行
    │   └── log-analyzer.md            #     ログ分析
    │
    ├── commands/                      #   スラッシュコマンド定義
    │   ├── add-feature.md             #     新機能追加ワークフロー
    │   ├── fix-bug.md                 #     バグ修正ワークフロー
    │   ├── refactor.md                #     リファクタリングワークフロー
    │   ├── review.md                  #     コードレビューワークフロー
    │   ├── run-tests.md               #     テスト実行・分析ワークフロー
    │   ├── update-docs.md             #     ドキュメント更新ワークフロー
    │   ├── add-scenario.md            #     シナリオ追加ワークフロー
    │   └── tune-prompt.md             #     プロンプトチューニングワークフロー
    │
    └── skills/                        #   スキル定義
        ├── python-standards/
        │   ├── SKILL.md               #     Pythonコーディング規約
        │   ├── examples.md            #     実装例集
        │   └── anti-patterns.md       #     アンチパターン集
        ├── pydantic-patterns/
        │   ├── SKILL.md               #     Pydanticモデル設計パターン
        │   ├── examples.md            #     実装例集
        │   └── validation-recipes.md  #     バリデーションレシピ集
        ├── prompt-engineering/
        │   ├── SKILL.md               #     LLMプロンプト設計原則
        │   ├── examples.md            #     プロンプト実装例集
        │   └── evaluation-guide.md    #     プロンプト評価ガイド
        └── test-standards/
            ├── SKILL.md               #     テスト設計・実装基準
            ├── examples.md            #     テスト実装例集
            └── fixture-patterns.md    #     フィクスチャパターン集
```

---

## 2. ルートディレクトリ

### 2.1 ファイル一覧と責務

| ファイル | 責務 | 編集頻度 | Git管理 |
|---|---|---|---|
| `CLAUDE.md` | Claude Code のマスター指示書。プロジェクトの全体像、開発原則、ドキュメント体系、.steering の運用ルールを記述 | 低（構造変更時のみ） | ○ |
| `README.md` | プロジェクト概要、セットアップ手順、実行方法、成果物の説明。外部公開向け | 中（リリースごと） | ○ |
| `pyproject.toml` | プロジェクトメタデータ、依存関係、ruff/mypy/pytest の設定 | 低（依存追加時） | ○ |
| `uv.lock` | 依存関係のロックファイル。`uv sync` で自動生成 | 自動 | ○ |
| `.env.example` | 環境変数のテンプレート。実際の値は含めない | 低 | ○ |
| `.gitignore` | Git除外ルール | 低 | ○ |
| `.python-version` | Python バージョン指定（`3.11` 等） | 極低 | ○ |

### 2.2 `.env.example` の内容

```env
# LLM API設定
CSDG_LLM_API_KEY=your-anthropic-api-key-here
CSDG_LLM_MODEL=claude-sonnet-4-20250514
CSDG_LLM_BASE_URL=https://api.anthropic.com

# パイプライン設定
CSDG_MAX_RETRIES=3
CSDG_INITIAL_TEMPERATURE=0.7
CSDG_OUTPUT_DIR=output

# 感情感度係数
CSDG_EMOTION_SENSITIVITY_STRESS=-0.3
CSDG_EMOTION_SENSITIVITY_MOTIVATION=0.4
CSDG_EMOTION_SENSITIVITY_FATIGUE=-0.2
```

### 2.3 `.gitignore` に含めるべきエントリ

```gitignore
# 環境変数（実値）
.env

# パイプライン出力
output/

# Python
__pycache__/
*.pyc
*.pyo
.mypy_cache/
.ruff_cache/
.pytest_cache/

# 仮想環境
.venv/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# uv
.uv/
```

---

## 3. `docs/` — 永続的ドキュメント

### 3.1 配置ルール

- すべてのドキュメントは Markdown 形式（`.md`）で記述する
- ファイル名はケバブケース（`kebab-case`）を使用する
- 画像などのアセットが必要な場合は `docs/assets/` サブディレクトリに配置する
- ドキュメント間の参照は相対パスで行う（例: `[技術設計書](./architecture.md)`）

### 3.2 ドキュメント一覧

| ファイル | 内容 | 主な読者 | 依存先 |
|---|---|---|---|
| `functional-design.md` | 機能要件、ユースケース、入出力仕様、品質基準 | 開発者、評価者 | `glossary.md` |
| `architecture.md` | システム構成、データフロー、モジュール設計、技術選定 | 開発者 | `glossary.md`, `functional-design.md` |
| `repository-structure.md` | ディレクトリ構成、ファイル配置規約、命名規則 | 開発者 | `architecture.md` |
| `development-guidelines.md` | コーディング規約、Git運用、テスト方針、PR手順 | 開発者 | `glossary.md`, `repository-structure.md` |
| `glossary.md` | プロジェクト固有の用語定義 | 全員 | なし（最下層） |

### 3.3 ドキュメントの依存関係

```
glossary.md                  ← 全ドキュメントの基盤（最下層）
  ↑
functional-design.md         ← 「何を作るか」
  ↑
architecture.md              ← 「なぜ・どう作るか」
  ↑
repository-structure.md      ← 「どこに置くか」
  ↑
development-guidelines.md    ← 「どう運用するか」
```

### 3.4 ドキュメント更新のルール

1. 用語の新規追加・変更は、まず `glossary.md` に反映してから他ドキュメントを更新する
2. 機能要件の追加・変更は `functional-design.md` を先に更新し、影響する `architecture.md` と `repository-structure.md` を追随させる
3. ドキュメントの変更は `.steering/` に設計記録を残す

---

## 4. `csdg/` — メインアプリケーションパッケージ

### 4.1 パッケージ構造の設計原則

- **フラットパッケージ:** ネストは最大2階層（`csdg/` と `csdg/engine/`）に留める
- **単一責任:** 各モジュールは1つの明確な責務のみを持つ
- **依存方向:** `main.py` → `engine/pipeline.py` → `engine/actor.py` / `engine/critic.py` → `schemas.py` の一方向
- **循環禁止:** モジュール間の循環参照は厳禁。`schemas.py` は他の `csdg/` モジュールを `import` しない

### 4.2 モジュール一覧と責務

| モジュール | 責務 | 主な依存先 | テスト |
|---|---|---|---|
| `__init__.py` | パッケージ初期化。`__version__` の定義 | なし | — |
| `main.py` | CLI引数の解析、パイプライン実行、ファイル出力、可視化呼び出し | `config`, `scenario`, `engine/pipeline`, `visualization` | `test_pipeline.py`(統合) |
| `config.py` | 環境変数・`.env` からの設定読み込み。`CSDGConfig` クラス | `pydantic-settings` | `test_config.py` |
| `schemas.py` | `DailyEvent`, `CharacterState`, `EmotionalDelta`, `LLMDeltaResponse`, `CriticScore`, `CriticResult`, `GenerationRecord`, `PipelineLog`, `MemoryExtraction` | `pydantic` | `test_schemas.py` |
| `scenario.py` | 7日分の `DailyEvent` リスト定義、初期状態 `h_0` 定義、バリデーション | `schemas` | `test_scenario.py` |
| `visualization.py` | `state_trajectory.png` の生成。`PipelineLog` → matplotlib グラフ | `matplotlib`, `schemas` | `test_visualization.py` |

### 4.3 `csdg/engine/` — パイプラインエンジン

| モジュール | 責務 | 主な依存先 | テスト |
|---|---|---|---|
| `__init__.py` | サブパッケージ初期化 | なし | — |
| `actor.py` | Phase 1 (状態遷移) と Phase 2 (コンテンツ生成) の実行。プロンプト読み込み・展開 | `schemas`, `llm_client`, `config` | `test_actor.py` |
| `critic.py` | Phase 3 (評価) の実行。`expected_delta` / `deviation` の算出、Pass/Reject判定 | `schemas`, `llm_client`, `config` | `test_critic.py` |
| `pipeline.py` | Day単位のループ、リトライ制御、Self-Healing、memory_buffer管理、ログ収集 | `actor`, `critic`, `schemas`, `config` | `test_pipeline.py` |
| `llm_client.py` | LLM API呼び出しの抽象クラス `LLMClient` と Anthropic Claude 実装 `AnthropicClient` | `anthropic`, `pydantic` | `test_actor.py`(モック) |

### 4.4 モジュール間の依存関係図

```
main.py
  ├─▶ config.py
  ├─▶ scenario.py ─▶ schemas.py
  ├─▶ visualization.py ─▶ schemas.py
  └─▶ engine/
       └─▶ pipeline.py
             ├─▶ actor.py
             │     ├─▶ schemas.py
             │     ├─▶ llm_client.py
             │     └─▶ config.py
             ├─▶ critic.py
             │     ├─▶ schemas.py
             │     ├─▶ llm_client.py
             │     └─▶ config.py
             ├─▶ schemas.py
             └─▶ config.py

※ schemas.py は最下層。他の csdg/ モジュールを import しない。
※ config.py は schemas.py のみに依存する。
※ 矢印は import 方向（依存方向）を示す。循環は禁止。
```

### 4.5 新規モジュール追加のルール

1. `csdg/` 直下に置くか `csdg/engine/` に置くかは、以下の基準で判断する:
   - パイプラインの3フェーズに直接関わる → `csdg/engine/`
   - パイプラインの外側（設定、シナリオ、可視化、ユーティリティ） → `csdg/`
2. 新規モジュール追加時は、対応するテストファイルを `tests/` に必ず作成する
3. `repository-structure.md`（本ドキュメント）を更新する
4. `CLAUDE.md` への影響がある場合は併せて更新する

---

## 5. `prompts/` — プロンプトモジュール

### 5.1 配置ルール

- プロンプトはすべて Markdown 形式（`.md`）で記述する
- ファイル名はパスカルケース + アンダースコア区切り（例: `System_Persona.md`）
- プロンプトファイル内にPythonコードを直接埋め込まない
- 動的データの注入には `{variable_name}` 形式のプレースホルダを使用する

### 5.2 ファイル一覧

| ファイル | 用途 | 使用Phase | プレースホルダ |
|---|---|---|---|
| `System_Persona.md` | キャラクターの不変ルール。全PhaseのSystemプロンプトとして使用 | 全Phase | なし（静的） |
| `Prompt_StateUpdate.md` | 感情推移の計算ルール | Phase 1 | `{previous_state}`, `{event}`, `{memory_buffer}` |
| `Prompt_Generator.md` | ブログ記事の構成・感情の言語化ルール | Phase 2 | `{current_state}`, `{event}`, `{memory_buffer}`, `{revision_instruction}` |
| `Prompt_Critic.md` | 評価基準・採点基準（1-5スコアの定義） | Phase 3 | `{diary_text}`, `{current_state}`, `{event}`, `{expected_delta}`, `{deviation}` |
| `Prompt_MemoryExtract.md` | 長期記憶の信念・テーマ抽出 | メモリ更新時 | `{evicted_entries}`, `{current_beliefs}`, `{current_themes}` |

### 5.3 プロンプト変更時の確認事項

1. `glossary.md` の用語定義と表現が一致しているか
2. ペルソナの禁則事項が維持されているか
3. プレースホルダ名が `actor.py` / `critic.py` のコードと一致しているか
4. 変更内容を `.steering/` に記録したか

---

## 6. `tests/` — テストコード

### 6.1 配置ルール

- テストファイル名は `test_` プレフィックスを付ける（pytest の自動検出対応）
- テストファイルと被テストモジュールは1対1で対応させる
- 共通フィクスチャは `conftest.py` に定義する
- テスト用の固定データ（モック入力・期待出力）は `tests/fixtures/` に配置する

### 6.2 ファイル一覧

| テストファイル | 被テストモジュール | テスト内容 |
|---|---|---|
| `test_schemas.py` | `csdg/schemas.py` | Pydanticモデルのバリデーション（正常系・異常系）、クランプ動作、シリアライズ |
| `test_scenario.py` | `csdg/scenario.py` | Day番号の連続性、emotional_impactの範囲、初期状態の妥当性 |
| `test_config.py` | `csdg/config.py` | 環境変数の読み込み、デフォルト値、temperature_schedule生成 |
| `test_actor.py` | `csdg/engine/actor.py` | 状態更新のバリデーション、日記生成の非空チェック（LLMモック使用） |
| `test_critic.py` | `csdg/engine/critic.py` | expected_delta算出、deviation算出、Pass/Reject判定ロジック |
| `test_pipeline.py` | `csdg/engine/pipeline.py` | リトライ制御、Best-of-N、フォールバック、メモリ管理（統合テスト） |
| `test_visualization.py` | `csdg/visualization.py` | グラフ生成の正常完了、ファイル出力の確認 |

### 6.3 `tests/fixtures/` — テスト用固定データ

| ファイル | 内容 | 用途 |
|---|---|---|
| `sample_state.json` | `CharacterState` のサンプルJSON | Actorのテストの入力データ |
| `sample_event.json` | `DailyEvent` のサンプルJSON | 全テストのイベント入力 |
| `sample_critic_score.json` | `CriticScore` のサンプルJSON（Pass/Reject両パターン） | Criticのテスト期待値 |
| `sample_diary.md` | サンプル日記テキスト | Criticのテスト入力 |

### 6.4 `conftest.py` — 共通フィクスチャ

```python
# conftest.py に定義すべきフィクスチャの一覧（概念的な定義）

@pytest.fixture
def sample_event() -> DailyEvent:
    """テスト用の DailyEvent インスタンス。"""

@pytest.fixture
def initial_state() -> CharacterState:
    """テスト用の初期状態 h_0。"""

@pytest.fixture
def sample_config() -> CSDGConfig:
    """テスト用の設定（APIキーはダミー値）。"""

@pytest.fixture
def mock_llm_client() -> LLMClient:
    """LLM APIをモックしたクライアント。"""
```

---

## 7. `output/` — パイプライン出力

### 7.1 配置ルール

- `output/` ディレクトリは `.gitignore` に追加し、Git管理しない
- パイプライン実行時に自動作成される
- 各実行で上書きされる（`--no-overwrite` オプションで抑制可能）

### 7.2 ファイル一覧

| ファイル | 形式 | 生成元 | 内容 |
|---|---|---|---|
| `day_01.md` 〜 `day_07.md` | Markdown (YAMLフロントマター付き) | `pipeline.py` | 日記本文 + メタデータ |
| `generation_log.json` | JSON | `pipeline.py` | パイプライン全実行ログ |
| `state_trajectory.png` | PNG (1200×800px) | `visualization.py` | 感情パラメータ推移グラフ |

### 7.3 ファイル名規則

- 日記ファイル: `day_XX.md`（XX は2桁ゼロ埋め。例: `day_01.md`, `day_07.md`）
- ログ・グラフ: 固定名称。バージョン管理が必要な場合はタイムスタンプ付きサブディレクトリ（`output/20250115_143000/`）を使用する

---

## 8. `.steering/` — 構造化作業ノート

### 8.1 配置ルール

- ディレクトリ名: `[YYYYMMDD]-[タスク名]/`（例: `20250115-implement-actor/`）
- タスク名はケバブケース（`kebab-case`）を使用する
- 1つの作業セッションにつき1つのディレクトリを作成する
- 作業完了後もディレクトリは削除しない（作業履歴として保持）

### 8.2 ディレクトリ内構成

```
.steering/
├── 20250115-implement-actor/
│   ├── requirement.md         # 要件定義
│   ├── design.md              # 実装アプローチ
│   ├── tasklist.md            # タスクリスト
│   ├── blockers.md            # (オプション) ブロッカー記録
│   └── decisions.md           # (オプション) 決定事項記録
│
├── 20250116-implement-critic/
│   ├── requirement.md
│   ├── design.md
│   └── tasklist.md
│
└── 20250118-tune-day4-prompt/
    ├── requirement.md
    ├── design.md
    ├── tasklist.md
    └── decisions.md
```

### 8.3 各ファイルの役割

| ファイル | 必須/任意 | 内容 |
|---|---|---|
| `requirement.md` | 必須 | 背景、実装内容、受け入れ条件、影響範囲 |
| `design.md` | 必須 | 実装アプローチ、変更対象ファイル、代替案と選定理由 |
| `tasklist.md` | 必須 | 実装・テスト・ドキュメント更新のチェックリスト |
| `blockers.md` | 任意 | ブロッカーの発生日時、原因、対応策、ステータス |
| `decisions.md` | 任意 | 重要な決定事項の背景、選択肢、決定内容、理由 |

### 8.4 Git管理方針

- `.steering/` はGit管理する（作業履歴は開発資産として価値がある）
- ただし、巨大なログやスクリーンショットは含めない

---

## 9. `.claude/` — Claude Code 拡張設定

### 9.1 全体構成

```
.claude/
├── agents/        # サブエージェント定義
├── commands/      # スラッシュコマンド定義
└── skills/        # スキル定義
```

### 9.2 `agents/` — サブエージェント

#### 配置ルール
- 1エージェント = 1 Markdownファイル
- ファイル名はケバブケース（例: `code-reviewer.md`）
- YAMLフロントマターに必須メタデータを記述する

#### フロントマター構造
```yaml
---
name: (サブエージェントの一意な識別子)
description: (目的の説明 — Claude Code が起動判断に使用する)
tools: (許可するツールのカンマ区切りリスト)
model: (sonnet / opus / haiku / inherit)
---
```

#### ファイル一覧

| ファイル | 用途 | カテゴリ |
|---|---|---|
| `code-reviewer.md` | コードの品質・規約準拠・潜在バグを検査 | レビュー |
| `test-analyzer.md` | テスト結果を分析し、失敗原因とカバレッジを報告 | レビュー |
| `security-checker.md` | セキュリティ上の脆弱性・機密情報の漏洩リスクを検査 | レビュー |
| `impact-analyzer.md` | コード変更の影響範囲を調査し、リスクを評価 | 情報収集 |
| `dependency-checker.md` | 依存パッケージの脆弱性・互換性・更新状況を確認 | 情報収集 |
| `file-finder.md` | 指定条件に合致するファイルやコードパターンを検索 | 情報収集 |
| `test-runner.md` | テストスイートを実行し、結果をレポート | 実行 |
| `build-executor.md` | ビルド・型チェック・リンターを実行し、結果をレポート | 実行 |
| `log-analyzer.md` | ログファイルを解析し、エラーパターンや異常を検出 | 実行 |

### 9.3 `commands/` — スラッシュコマンド

#### 配置ルール
- 1コマンド = 1 Markdownファイル
- ファイル名はケバブケース（例: `add-feature.md`）
- 各コマンドは単一責任の原則に従う

#### ファイル一覧

| ファイル | コマンド名 | 用途 |
|---|---|---|
| `add-feature.md` | `/add-feature` | 新機能追加の完全なワークフロー |
| `fix-bug.md` | `/fix-bug` | バグ修正の完全なワークフロー |
| `refactor.md` | `/refactor` | リファクタリングの完全なワークフロー |
| `review.md` | `/review` | コードレビューの完全なワークフロー |
| `run-tests.md` | `/run-tests` | テスト実行・分析の完全なワークフロー |
| `update-docs.md` | `/update-docs` | ドキュメント更新の完全なワークフロー |
| `add-scenario.md` | `/add-scenario` | DailyEvent追加の完全なワークフロー |
| `tune-prompt.md` | `/tune-prompt` | プロンプトチューニングの完全なワークフロー |

### 9.4 `skills/` — スキル定義

#### 配置ルール
- 1スキル = 1 サブディレクトリ（ケバブケース）
- 各サブディレクトリに `SKILL.md`（エントリポイント）を必ず配置する
- 補足資料（実装例、アンチパターン等）は同ディレクトリ内に別ファイルとして配置する

#### ディレクトリ構造
```
skills/
├── python-standards/
│   ├── SKILL.md               # メインスキル定義
│   ├── examples.md            # 実装例集
│   └── anti-patterns.md       # アンチパターン集
├── pydantic-patterns/
│   ├── SKILL.md
│   ├── examples.md
│   └── validation-recipes.md  # バリデーションレシピ集
├── prompt-engineering/
│   ├── SKILL.md
│   ├── examples.md
│   └── evaluation-guide.md    # プロンプト評価ガイド
└── test-standards/
    ├── SKILL.md
    ├── examples.md
    └── fixture-patterns.md    # フィクスチャパターン集
```

#### SKILL.md のフロントマター構造
```yaml
---
name: (スキルの一意な識別子)
description: (スキルの目的と使用場面)
allowed-tools: (許可するツールのリスト)
---
```

---

## 10. 命名規則一覧

### 10.1 ファイル名

| カテゴリ | 規則 | 例 |
|---|---|---|
| Pythonモジュール | スネークケース (`snake_case`) | `llm_client.py`, `config.py` |
| テストファイル | `test_` + 被テストモジュール名 | `test_schemas.py`, `test_actor.py` |
| ドキュメント | ケバブケース (`kebab-case`) | `functional-design.md`, `glossary.md` |
| プロンプト | パスカルケース + アンダースコア | `System_Persona.md`, `Prompt_Critic.md` |
| サブエージェント | ケバブケース | `code-reviewer.md`, `test-runner.md` |
| スラッシュコマンド | ケバブケース | `add-feature.md`, `fix-bug.md` |
| スキルディレクトリ | ケバブケース | `python-standards/`, `test-standards/` |
| 出力日記ファイル | `day_` + 2桁ゼロ埋め | `day_01.md`, `day_07.md` |
| .steering ディレクトリ | `[YYYYMMDD]-[ケバブケース]` | `20250115-implement-actor/` |

### 10.2 Python コード内

| カテゴリ | 規則 | 例 |
|---|---|---|
| クラス名 | パスカルケース (`PascalCase`) | `CharacterState`, `CriticScore`, `AnthropicClient` |
| 関数名・メソッド名 | スネークケース (`snake_case`) | `update_state()`, `compute_deviation()` |
| 変数名 | スネークケース | `current_state`, `retry_count` |
| 定数 | アッパースネークケース (`UPPER_SNAKE_CASE`) | `EMOTION_SENSITIVITY`, `MAX_RETRIES` |
| プライベート | アンダースコアプレフィックス | `_build_prompt()`, `_clamp()` |
| 型エイリアス | パスカルケース | `StateDict = dict[str, float]` |

### 10.3 環境変数

| 規則 | 例 |
|---|---|
| `CSDG_` プレフィックス + アッパースネークケース | `CSDG_LLM_API_KEY`, `CSDG_MAX_RETRIES` |

---

## 11. ファイル追加・変更時のチェックリスト

新規ファイルを追加する場合、または既存ファイルの配置を変更する場合は、以下を確認する。

### 新規 Python モジュール追加時

- [ ] `csdg/` または `csdg/engine/` のどちらに配置するか判断した（§4.5の基準に従う）
- [ ] 対応するテストファイル `tests/test_*.py` を作成した
- [ ] 本ドキュメント（`repository-structure.md`）のモジュール一覧を更新した
- [ ] `CLAUDE.md` への影響を確認した
- [ ] 循環参照が発生しないことを確認した

### 新規プロンプトファイル追加時

- [ ] `prompts/` に配置した
- [ ] ファイル名はパスカルケース + アンダースコア区切りに従っている
- [ ] 使用するPhaseを明確にした
- [ ] プレースホルダ名をコードと合わせた
- [ ] 本ドキュメントのプロンプト一覧を更新した

### 新規サブエージェント追加時

- [ ] `.claude/agents/` に配置した
- [ ] YAMLフロントマターに `name`, `description`, `tools`, `model` を記述した
- [ ] `CLAUDE.md` のサブエージェント一覧テーブルを更新した
- [ ] 本ドキュメントのエージェント一覧を更新した

### 新規スラッシュコマンド追加時

- [ ] `.claude/commands/` に配置した
- [ ] 単一責任の原則に従っている
- [ ] ステップが具体的で順序が明確である
- [ ] `CLAUDE.md` のスラッシュコマンド一覧テーブルを更新した
- [ ] 本ドキュメントのコマンド一覧を更新した

### 新規スキル追加時

- [ ] `.claude/skills/[スキル名]/` ディレクトリを作成した
- [ ] `SKILL.md` をエントリポイントとして配置した
- [ ] YAMLフロントマターに `name`, `description`, `allowed-tools` を記述した
- [ ] 必要に応じて `examples.md` 等の補足資料を配置した
- [ ] `CLAUDE.md` のスキル一覧テーブルを更新した
- [ ] 本ドキュメントのスキル一覧を更新した
