# CSDG - Cognitive-State Diary Generator

体系的認知モデルに基づく AI キャラクター日記生成システム。
Actor-Critic 型の敵対的検証ループにより、7 日間の一人称ブログ日記を自動生成する。

## 概要

CSDG は、架空のキャラクター「三浦とこみ」(26 歳、バックエンドエンジニア / 元哲学大学院生) の内面を
構造化された認知状態モデルとして管理し、日々のイベントに対する感情変化と日記テキストを生成する。
三浦とこみが運営する個人ブログ「余白のログ」の記事として、1 日あたり約 400 文字のブログ日記を出力する。

### 3-Phase パイプライン

```
Day 1 〜 Day 7 ループ:

  Phase 1: State Update     ─ イベント x_t から内部状態 h_t を更新
       ↓                      (半数式化: 決定論的骨格 + LLM delta 補正)
  Phase 2: Content Gen      ─ h_t に基づきブログ日記テキストを生成
       ↓
  Phase 3: Critic Eval      ─ 3層評価 (RuleBased / Statistical / LLMJudge)
       ↓
  Pass → 保存 / Reject → リトライ (最大3回, 区分線形 Temperature Decay)
                          + 構造的制約違反時はボーナス再試行 (予算外1回)
                          + Phase 1 偏差ガード (deviation > 0.10 でソフト補正)
```

### 主な特徴

- **状態空間モデル** -- 感情パラメータを管理 (fatigue: `0.0`〜`1.0`、motivation/stress: `-1.0`〜`1.0`)
- **HumanCondition (人間的コンディション)** -- イベント非依存の生物的・心理的状態 (睡眠の質、身体的エネルギー、気分ベースライン、認知負荷、感情的葛藤) を自動導出し、日記の文体に反映
- **半数式化された状態遷移** -- 決定論的な数式ベース + LLM による解釈的補正で再現性を確保
- **3 層 Critic + 段階化ボーナス** -- ルールベース検証 (L1) + 統計的検証 (L2) + LLM 定性評価 (L3) の重み付き統合 (0.40 / 0.35 / 0.25)。L1/L2 の各指標に sweet spot / acceptable / penalty の多段階ボーナスを設け、加重平均が integer 境界を跨ぐ十分な帯域幅を確保。base score 2.5 と組み合わせ、最終スコアの弁別力を実現。emotional_plausibility は 6 段階 (L1) / 7 段階 (L2) のグラデーションで評価
- **Veto 機構** -- 禁止一人称・文字数極端逸脱・高 trigram 重複等の致命的違反に対し、安全制限をバイパスして強制的にスコア上限を適用
- **2 層メモリ** -- 短期記憶 (直近 3 日) + 長期記憶 (信念・テーマ・転換点)
- **Self-Healing** -- LLM 出力のパースエラーに対するリトライ + Best-of-N フォールバック (構造的違反ペナルティ付き) + API 過負荷時の指数バックオフリトライ
- **Phase 1 偏差ガード** -- State Update 後の deviation が閾値 (0.10) を超過した場合、expected_delta 方向にソフト補正 (α=0.5) を適用し、Phase 2/3 リトライでは修正不能な deviation 超過を防止

### 品質制御 (正規化項)

#### 書き出しパターンの多様化

比喩型 / 五感型 / 会話型 / 問い型 / 断片型 / 回想型 の 6 パターンを自動分類・蓄積。ホワイトリスト + 具体例方式で使用可能パターンと残り回数を Day 依存で提示 (Day 1-5: 各パターン 1 回まで、Day 6-7: 2 回まで)。冒頭 80 文字からの特徴語検出、句点分割による断片型検出 (3+ フレーズ各 10 文字以下)、「だろう」末尾マッチによる問い型検出、五感キーワード (匂い / 音 / 光 / 温度 / 風 / 空気 / 肌) に対応。「人名 + 声/言葉/一言」パターンは五感型より優先して会話型に分類 (会話の残響検出)。冒頭テキストの Day 間 trigram 重複チェック (overlap > 50% で違反) により、テキストレベルの書き出しコピーを防止。

#### 余韻構文パターンの多様化

「〜だろう系 / 〜かもしれない系 / 〜ずにいる系 / 〜ている系 / 行動締め系 / 引用系 / 体言止め系 / 省略系 / その他」の 9 パターンに自動分類。Day 依存の上限制御 (Day 1-5: 各パターン 1 回まで、Day 6-7: 2 回まで)。末尾 2 文をスキャン対象とし、〜ている系は最終文だけでなく末尾 2 文目の文末もチェック。行動締め系は 12 語の動作動詞 (閉じた / 消した / 置いた / 立った / 歩いた / 座った / 開けた / 飲んだ / 落ちた / 捨てた / 入れた / しまった) を検出。体言止め系は 40 文字以下の漢字/カタカナ終端を判定。未使用パターンを「推奨」として先頭配置し、多様性を誘導。過去の余韻テキスト原文を Generator プロンプトに注入し、テキストレベルの事前重複回避を実現。余韻テキストの Day 間 trigram 重複チェック (overlap > 50%) により、類似した余韻の反復を防止。

#### 場面構造パターン追跡

帰路型 / 古書店型 / 会議型 等の場面構造を自動分類。帰路型・古書店型は最大 2 回、他は最大 3 回。前日と同一構造の連続使用を検出・禁止。使用可能な代替構造を提示。

#### 概念語・主題語の頻度制御

- **per-day 制限**: 各主題語 (効率 / 非効率 / 最適化 / 自動化) を 3 回/日 以下に制限 (Day 1 から常時注入)
- **累計制限**: ソフトリミット 10 回超過で per-day 制限強化、ハードリミット 18 回超過で使用禁止
- **イベント記述警告**: イベント記述に主題語が含まれる場合は代替表現への置換を明示的に警告

#### その他の反復防止

- **余韻フィードバック** -- 直近 3 日の末尾段落を蓄積し、フレーズ反復を抑制。余韻間の trigram 類似度チェック
- **シーン描写の反復防止** -- 場所・物のマーカー語 (30 語) を含むキーフレーズを Day 間で蓄積
- **シーンマーカー出現日数追跡** -- マーカー語の出現日数を追跡し、2 日以上で使用自粛、3 日以上で使用禁止
- **哲学者引用カウンター** -- 同一人物への言及を 7 日間で最大 2 回に制限
- **修辞疑問文の反復防止** -- 修辞疑問文を抽出・蓄積 (直近 5 件)、同一構文の再使用を禁止

#### 構造的制約バリデーション (7 項目)

Critic 評価の前に軽量チェックを実行し、違反内容をリビジョン指示に合流:

1. 余韻パターン上限 (Day 依存: Day 1-5 は各 1 回、Day 6-7 は各 2 回)
2. 場面構造の連続使用 (前日と同一は禁止)
3. 場面構造の上限超過
4. 主題語 per-day 上限 (3 回/日)
5. 書き出しパターン上限超過 (Day 依存: Day 1-5 は各 1 回、Day 6-7 は各 2 回)
6. 冒頭テキスト Day 間 trigram 重複 (overlap > 50%)
7. 余韻テキスト Day 間 trigram 重複 (overlap > 50%)

Critic Pass + 構造的違反時は**ボーナス再試行** (リトライ予算を消費しない 1 回限定の追加試行) を実行。Best-of-N フォールバック時は構造的違反数をペナルティとしてスコアから減算し、違反のない候補を優先選択。

#### 高インパクト日の制御

- `|emotional_impact| > 0.7` の日に対し、文体変化の方向性を誘導 (短文連打、比喩崩壊、哲学的考察の中断等)
- 初回リトライのみ Temperature を初期値 (0.7) に維持し、2 回目以降は通常の Temperature Decay を適用

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
# .env を編集し、使用するプロバイダーに応じた API キーを設定
# (CSDG_ANTHROPIC_API_KEY または CSDG_GEMINI_API_KEY)
```

### 環境変数

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `CSDG_LLM_PROVIDER` | No | `anthropic` | LLM プロバイダー (`anthropic` or `gemini`) |
| `CSDG_ANTHROPIC_API_KEY` | provider=anthropic 時 | - | Anthropic API キー |
| `CSDG_ANTHROPIC_MODEL` | No | `claude-sonnet-4-20250514` | 使用する Claude モデル |
| `CSDG_GEMINI_API_KEY` | provider=gemini 時 | - | Google Gemini API キー |
| `CSDG_GEMINI_MODEL` | No | `gemini-2.0-flash` | 使用する Gemini モデル |
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
  critic_log.jsonl          # Critic 評価ログ (JSON Lines)
  state_trajectory.png      # 感情パラメータ + CriticScore の推移グラフ
```

### 品質検証

```bash
# 品質サマリレポート (8 項目の品質基準で PASS/FAIL を判定)
python scripts/quality_report.py output/generation_log.json

# Critic 弁別力検証
python scripts/verify_critic_discrimination.py output/generation_log.json
```

`quality_report.py` は生成結果から以下の品質基準を検証する:

| 基準 | 目標 |
|------|------|
| 書き出し多様性 | 5 種以上 / 7 日 |
| 余韻多様性 | 5 種以上 / 7 日 |
| 「その他」余韻 | 1 回以下 |
| 構造連続使用 | なし |
| 古書店型上限 | 2 回以下 |
| 帰路型上限 | 2 回以下 |
| Critic 全 Day Pass | 7/7 |
| フォールバック率 | 1/7 以下 |

## アーキテクチャ

### モジュール構成

```
csdg/
  schemas.py              # Pydantic データモデル (HumanCondition, CharacterState, CriticScore 等)
  config.py               # 環境変数ベースの設定管理
  scenario.py             # 7日分のイベント + 初期状態
  engine/
    actor.py              # Phase 1 (状態更新) + Phase 2 (日記生成)
    critic.py             # Phase 3 (3層評価: RuleBased / Statistical / LLMJudge)
    critic_log.py         # CriticLog 蓄積・フィードバック注入
    constants.py          # 共有定数 (パターン例 / 閾値 / 制限値)
    state_transition.py   # 半数式化された状態遷移 (decay + event + LLM delta + HumanCondition 自動導出)
    memory.py             # 2層メモリ (ShortTerm + LongTerm)
    pipeline.py           # パイプライン制御 (リトライ / Temperature Decay / Best-of-N)
    llm_client.py         # LLM API 抽象化 (Anthropic Claude 実装)
    prompt_loader.py      # プロンプトファイル読み込みユーティリティ
  main.py                 # CLI エントリポイント
  visualization.py        # 状態推移グラフ生成

scripts/
  quality_report.py                  # 品質サマリレポート (8 基準 PASS/FAIL)
  verify_critic_discrimination.py    # Critic 弁別力検証スクリプト

prompts/
  System_Persona.md       # キャラクター定義 (三浦とこみ)
  Prompt_StateUpdate.md   # Phase 1 プロンプト
  Prompt_Generator.md     # Phase 2 プロンプト
  Prompt_Critic.md        # Phase 3 プロンプト
  Prompt_MemoryExtract.md # 長期記憶の信念・テーマ抽出
  System_MemoryManager.md # メモリ管理システムプロンプト

docs/
  functional-design.md    # 機能設計書
  architecture.md         # 技術設計書
  repository-structure.md # リポジトリ構造定義書
  development-guidelines.md # 開発ガイドライン
  glossary.md             # ユビキタス言語定義
  erre-design.md          # ERRE 設計思想 (Extract-Reverify-Reimplement-Express)
```

### Critic 3 層構造

| 層 | クラス | 種別 | 重み | 検証内容 |
|---|---|---|---|---|
| Layer 1 | `RuleBasedValidator` | 決定論的 | 0.40 | 文字数 (段階化)、わたし使用頻度 (段階化 + 過剰使用ペナルティ)、余韻「......」(段階化)、前日重複率 (段階化)、感情 deviation 6 段階評価 (0.05/0.08/0.12/0.15/0.20 閾値)、余韻 trigram 類似度、禁止一人称検出 + Veto |
| Layer 2 | `StatisticalChecker` | 数値的 | 0.35 | 平均文長 (段階化)、句読点頻度 (段階化)、文数 (段階化)、疑問文比率 (段階化)、deviation 7 段階連続スケーリング (0.08/0.12/0.18/0.30/0.40/0.60 閾値)、断定文比率、高インパクト日文体検証 |
| Layer 3 | `LLMJudge` | 定性的 | 0.25 | LLM による temporal / emotional / persona 評価 (L1/L2 結果を参照基準として構造化注入) |

最終スコアは純粋な加重平均の `round()` で決定 (base score 2.5)。Veto 対象の致命的違反 (禁止一人称 / 文字数極端逸脱 / 高 trigram 重複) は安全制限をバイパスして強制的にスコア上限を適用。

### 状態遷移の数式

```
base[param] = prev[param] * (1 - decay_rate) + event_impact * event_weight
h_t[param]  = base + llm_delta[param] * llm_weight + noise
clamp(h_t[param], lo, 1.0)    # lo = 0.0 for fatigue, -1.0 for others
```

### ERRE 設計思想

CSDG は **ERRE (Extract-Reverify-Reimplement-Express)** フレームワークに基づく。哲学から「人間の思考を深める構造」を抽出し、科学的方法で再検証、システムで再実装、人間に伝達可能な形で表現する。核となるコンセプトは「意図的非効率」-- 効率が捨象する認知プロセスを保存し、日記という形式で表現する。

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
| 1 | neutral | -0.15 | 自動化スクリプト完成、空虚感 |
| 2 | positive | +0.5 | 古書店で岡倉天心『茶の本』初版を発見 |
| 3 | negative | -0.4 | コードレビューで「動くけど読めない」と指摘 |
| **4** | **negative** | **-0.8** | **深夜の過去ブログ遡り、過去の自分との対峙 (転機)** |
| 5 | positive | +0.3 | ミナとの偶然の再会、「ブログに書いたら」 |
| 6 | positive | +0.35 | ラムダ式を関数に書き直し、『茶の本』の一節 |
| 7 | positive | +0.25 | カフェで 1 週間の振り返り、問いの継続 |

## ライセンス

MIT
