# CSDG - Cognitive-State Diary Generator

体系的認知モデルに基づく AI キャラクター日記生成システム。
Actor-Critic 型の敵対的検証ループにより、7 日間の一人称ブログ日記を自動生成する。

## 概要

CSDG は、架空のキャラクター「三浦とこみ」(26 歳、バックエンドエンジニア / 元哲学大学院生) の内面を
構造化された認知状態モデルとして管理し、日々のイベントに対する感情変化と日記テキストを生成する。

### 3-Phase パイプライン

```
Day 1 〜 Day 7 ループ:

  Phase 1: State Update     ─ イベント x_t から内部状態 h_t を更新
       ↓                      (半数式化: 決定論的骨格 + LLM delta 補正)
  Phase 2: Content Gen      ─ h_t に基づきブログ日記テキストを生成
       ↓
  Phase 3: Critic Eval      ─ 3層評価 (RuleBased / Statistical / LLMJudge)
       ↓
  Pass → 保存 / Reject → リトライ (最大3回, Temperature Decay)
```

### 主な特徴

- **状態空間モデル** -- 感情パラメータ (fatigue / motivation / stress) を `-1.0` 〜 `1.0` で管理
- **半数式化された状態遷移** -- 決定論的な数式ベース + LLM による解釈的補正で再現性を確保
- **3 層 Critic** -- ルールベース検証 + 統計的検証 + LLM 定性評価の重み付き統合
- **2 層メモリ** -- 短期記憶 (直近 3 日) + 長期記憶 (信念・テーマ・転換点)
- **Self-Healing** -- LLM 出力のパースエラーに対するリトライ + Best-of-N フォールバック

## セットアップ

### 前提条件

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (推奨) または pip

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/mikotomiura/cognitive-State-Diary-generator.git
cd cognitive-State-Diary-generator

# 依存関係のインストール
uv sync

# 環境変数を設定
cp .env.example .env
# .env を編集し CSDG_LLM_API_KEY に Anthropic API キーを設定
```

### 環境変数

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `CSDG_LLM_API_KEY` | Yes | - | Anthropic API キー |
| `CSDG_LLM_MODEL` | No | `claude-sonnet-4-20250514` | 使用する Claude モデル |
| `CSDG_MAX_RETRIES` | No | `3` | Critic Reject 時の最大リトライ回数 |
| `CSDG_INITIAL_TEMPERATURE` | No | `0.7` | 初回生成の Temperature |
| `CSDG_OUTPUT_DIR` | No | `output` | 出力ディレクトリ |

## 使い方

### 全 7 日分を生成

```bash
python -m csdg.main
```

### 特定の Day のみ実行

```bash
python -m csdg.main --day 4
```

### オプション

```bash
python -m csdg.main --help

# --day N              特定の Day のみ実行
# --output-dir PATH    出力先ディレクトリを指定
# --verbose            デバッグログを出力
# --skip-visualization グラフ生成をスキップ
# --dry-run            設定確認のみ (API 呼び出しなし)
```

### 出力

```
output/
  day_01.md 〜 day_07.md    # 生成された日記 (YAML frontmatter + Markdown)
  generation_log.json       # 実行ログ (リトライ数、スコア推移等)
  state_trajectory.png      # 感情パラメータ + CriticScore の推移グラフ
```

## アーキテクチャ

### モジュール構成

```
csdg/
  schemas.py              # Pydantic データモデル (CharacterState, CriticScore 等)
  config.py               # 環境変数ベースの設定管理
  scenario.py             # 7日分のイベント + 初期状態
  engine/
    actor.py              # Phase 1 (状態更新) + Phase 2 (日記生成)
    critic.py             # Phase 3 (3層評価: RuleBased / Statistical / LLMJudge)
    state_transition.py   # 半数式化された状態遷移 (decay + event + LLM delta)
    memory.py             # 2層メモリ (ShortTerm + LongTerm)
    pipeline.py           # パイプライン制御 (リトライ / Temperature Decay / Best-of-N)
    llm_client.py         # LLM API 抽象化 (Anthropic Claude 実装)
  main.py                 # CLI エントリポイント
  visualization.py        # 状態推移グラフ生成

prompts/
  System_Persona.md       # キャラクター定義 (三浦とこみ)
  Prompt_StateUpdate.md   # Phase 1 プロンプト
  Prompt_Generator.md     # Phase 2 プロンプト
  Prompt_Critic.md        # Phase 3 プロンプト
```

### Critic 3 層構造

| 層 | クラス | 種別 | 重み | 検証内容 |
|---|---|---|---|---|
| Layer 1 | `RuleBasedValidator` | 決定論的 | 0.3 | 文字数、絵文字、重複率、方向整合性 |
| Layer 2 | `StatisticalChecker` | 数値的 | 0.2 | 平均文長、deviation 分析、断定文比率 |
| Layer 3 | `LLMJudge` | 定性的 | 0.5 | LLM による temporal / emotional / persona 評価 |

### 状態遷移の数式

```
base[param] = prev[param] * (1 - decay_rate) + event_impact * event_weight
h_t[param]  = base + llm_delta[param] * llm_weight + noise
clamp(h_t[param], -1.0, 1.0)
```

## 開発

### テスト

```bash
# 全テスト実行
pytest tests/ -v

# カバレッジ付き
pytest tests/ -v --cov=csdg
```

### 型チェック・リンター

```bash
# 型チェック (strict mode)
mypy csdg/ --strict

# リンター
ruff check csdg/

# フォーマッター
ruff format csdg/
```

### シナリオ (7 日間のイベント)

| Day | event_type | impact | 概要 |
|---|---|---|---|
| 1 | neutral | +0.2 | 自動化スクリプト完成、虚しさ |
| 2 | positive | +0.6 | 古書店で西田幾多郎の初版本を発見 |
| 3 | negative | -0.5 | コードレビュー会で設計提案を一蹴される |
| **4** | **negative** | **-0.9** | **全社 AI 自動化ロードマップ発表 (転機)** |
| 5 | neutral | +0.4 | ミナとの会話で「あなたは表現者だ」 |
| 6 | neutral | +0.5 | 大学院時代の現象学ノートを発見 |
| 7 | positive | +0.5 | 暗黙知の可視化を職場に提案 |

## ライセンス

MIT
