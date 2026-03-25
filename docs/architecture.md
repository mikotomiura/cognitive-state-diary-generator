# 技術設計書 (Architecture Document)

> **目的:** CSDG（Cognitive-State Diary Generator）のシステム全体像、データフロー、モジュール構成、技術選定の根拠、およびエラーハンドリング戦略を開発者向けに定義する。
> 本ドキュメントは実装の「なぜそう設計するのか」を記述し、「何を作るか」は `functional-design.md` に、「どこに置くか」は `repository-structure.md` に委譲する。

---

## 1. システム全体像

### 1.1 アーキテクチャ概要

CSDGは、LLMを用いた7日間連続テキスト生成システムである。
以下の3つの設計課題を解決するために、Actor-Critic型の3フェーズパイプラインを採用する。

| 設計課題 | 解決アプローチ | 該当セクション |
|---|---|---|
| コンテキストの劣化 | 状態空間モデルとエピソード記憶の分離 | §2 |
| ペルソナ破綻 | Actor-Critic型 敵対的検証ループ | §3 |
| LLM出力の非決定性 | Self-Healing パイプライン | §4 |

### 1.2 処理の全体フロー

```
┌─────────────────────────────────────────────────────────────────────┐
│                     メインループ (Day 1 〜 Day 7)                    │
│                                                                     │
│  ┌───────────┐    ┌────────────┐    ┌────────────┐                 │
│  │  Phase 1   │───▶│  Phase 2   │───▶│  Phase 3   │                │
│  │ State      │    │ Content    │    │ Critic     │                │
│  │ Update     │    │ Generation │    │ Evaluation │                │
│  └───────────┘    └────────────┘    └─────┬──────┘                │
│       ▲                                    │                        │
│       │                              ┌─────▼──────┐                │
│       │                              │  Pass?     │                │
│       │                              └─────┬──────┘                │
│       │                           Yes │         │ No               │
│       │                               ▼         ▼                  │
│       │                        ┌──────────┐ ┌──────────┐           │
│       │                        │ 日記保存  │ │ リトライ  │           │
│       │                        │ ログ記録  │ │ (最大3回) │           │
│       │                        └──────────┘ └─────┬────┘           │
│       │                                           │                │
│       │                                    ┌──────▼─────┐          │
│       │                                    │ 上限超過?  │          │
│       │                                    └──────┬─────┘          │
│       │                                    Yes │                   │
│       │                                        ▼                   │
│       │                                 ┌────────────┐             │
│       │                                 │ Best-of-N  │             │
│       │                                 │ Fallback   │             │
│       │                                 └────────────┘             │
│       │                                                            │
│       └──── h_t を h_{t-1} として次の Day へ引き継ぐ ──────────────┘
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 データの流れ（入出力概要）

```
[入力]                          [処理]                        [出力]
scenario.py                     main.py                       output/
  DailyEvent × 7          ───▶  engine/pipeline.py     ───▶    day_01.md 〜 day_07.md
                                  ├─ engine/actor.py            generation_log.json
config.py                        └─ engine/critic.py           state_trajectory.png
  EMOTION_SENSITIVITY
                                prompts/
prompts/                          System_Persona.md
  *.md (4ファイル)                Prompt_StateUpdate.md
                                  Prompt_Generator.md
schemas.py                       Prompt_Critic.md
  Pydantic Models
```

---

## 2. 状態管理アーキテクチャ

### 2.1 状態空間モデル

キャラクターの内部状態を **潜在変数 `h_t`** として構造化し、テキスト履歴とは独立に管理する。

```
h_t = f(h_{t-1}, x_t, persona)

  h_{t-1} : 前日の CharacterState (JSON)
  x_t     : 今日の DailyEvent (JSON)
  persona : System_Persona.md (テキスト)
  f       : LLM (Actor) による状態遷移関数
```

**設計上の重要な判断:**
- `h_t` は必ず `CharacterState` Pydanticモデルとしてバリデーションされる
- テキスト本文（日記）は `h_t` に含めない。Phase 1 と Phase 2 を分離することで、JSONパースエラーのリスクを低減する
- 連続変数（`fatigue`, `motivation`, `stress`）は `-1.0` 〜 `1.0` にクランプする

### 2.2 メモリアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                     LLM プロンプト                        │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  意味記憶 (常に含まれる)                          │    │
│  │  System_Persona.md                               │    │
│  │  - 性格の核、口調ルール、禁則事項                  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  エピソード記憶 (スライディングウィンドウ)          │    │
│  │  memory_buffer: list[str]  ← 最大3件             │    │
│  │  [Day t-3 要約, Day t-2 要約, Day t-1 要約]      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  現在状態 (Phase ごとに異なる)                     │    │
│  │  h_{t-1} or h_t + x_t                            │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**スライディングウィンドウの挙動:**

| 現在の Day | memory_buffer の内容 | 備考 |
|---|---|---|
| Day 1 | `[]` | 初日は記憶なし |
| Day 2 | `[Day1要約]` | |
| Day 3 | `[Day1要約, Day2要約]` | |
| Day 4 | `[Day1要約, Day2要約, Day3要約]` | ウィンドウが満杯 |
| Day 5 | `[Day2要約, Day3要約, Day4要約]` | Day1が押し出される |
| Day 6 | `[Day3要約, Day4要約, Day5要約]` | |
| Day 7 | `[Day4要約, Day5要約, Day6要約]` | |

**ウィンドウサイズの根拠:**
- 3日分にすることで、コンテキストウィンドウの消費を抑えつつ、物語の連続性に必要な直近の文脈を保持する
- Day 4（転機）の記憶が Day 7（着地）でも保持されるため、物語アークの核心的接続を維持できる

**2層メモリ構造 (`engine/memory.py`):**

スライディングウィンドウから押し出されたエントリの情報を長期記憶に蓄積する:

| 層 | クラス | 内容 |
|---|---|---|
| ShortTermMemory | `schemas.ShortTermMemory` | 直近N日の生テキスト要約 (従来の memory_buffer 相当) |
| LongTermMemory | `schemas.LongTermMemory` | 信念 (beliefs), 繰り返しテーマ (recurring_themes), 転換点 (turning_points) |

MemoryManager が2層を統合管理し、Actor/Critic にコンテキストを提供する。

### 2.3 状態遷移の半数式化 (`engine/state_transition.py`)

状態遷移を決定論的骨格 + LLM delta 補正で行う:

```
base[param] = prev[param] * (1 - decay_rate) + event_impact * event_weight
clipped_delta = clamp(llm_delta[param], -max_llm_delta, +max_llm_delta)
h_t[param] = base + clipped_delta * llm_weight + noise
clamp(h_t[param], -1.0, 1.0)
```

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `decay_rate` | 0.1 | 自然減衰 (ストレスは放っておくと下がる等) |
| `event_weight` | 0.6 | イベントの直接影響 |
| `llm_weight` | 0.3 | LLM による解釈的補正 |
| `noise_scale` | 0.05 | 微小ランダム性 (自然さのため) |
| `max_llm_delta` | 0.3 | LLM delta の絶対値上限 (安定性保証) |

**LLM delta 制約**: `max_llm_delta` により各軸の1ステップあたり変化量を制約し、
状態空間モデルとしての安定性 (bounded dynamics) を保証する。

**Temperature スケジュール**: 指数減衰 `temp = final + (initial - final) * exp(-decay_constant * i)` を採用。
序盤は探索的 (高 temperature)、中盤以降は急速に安定し、物語の着地が安定する。

新スキーマ: `EmotionalDelta` (fatigue/motivation/stress の変化量)

### 2.4 状態遷移のバリデーション

```python
# Phase 1 の出力バリデーション（概念的なコード）
def validate_state_transition(prev: CharacterState, curr: CharacterState, event: DailyEvent) -> None:
    """状態遷移の妥当性を検証する。"""

    # 1. 連続変数の範囲チェック
    for field in ["fatigue", "motivation", "stress"]:
        value = getattr(curr, field)
        if not (-1.0 <= value <= 1.0):
            raise ValueError(f"{field} が範囲外: {value}")

    # 2. memory_buffer のサイズチェック
    if len(curr.memory_buffer) > 3:
        raise ValueError(f"memory_buffer が上限超過: {len(curr.memory_buffer)}")

    # 3. relationships のキーが既知の人物のみか
    known_characters = {"深森那由他", "ミナ"}
    for name in curr.relationships:
        if name not in known_characters:
            raise ValueError(f"未知の人物: {name}")
```

---

## 3. パイプライン詳細設計

### 3.1 Phase 1: 状態遷移 (State Update)

**責務:** イベント `x_t` を受けて、前日の状態 `h_{t-1}` を今日の状態 `h_t` に更新する。

**入力:**
| 項目 | ソース | 形式 |
|---|---|---|
| ペルソナ定義 | `prompts/System_Persona.md` | System Prompt (テキスト) |
| 状態遷移ルール | `prompts/Prompt_StateUpdate.md` | User Prompt (テキスト) |
| 前日の状態 `h_{t-1}` | 前回Phase 1の出力 / `h_0` | JSON (`CharacterState`) |
| 今日のイベント `x_t` | `scenario.py` | JSON (`DailyEvent`) |

**出力:** `CharacterState` (JSON / Structured Outputs)

**LLM呼び出し設定:**
| パラメータ | 値 | 理由 |
|---|---|---|
| `response_format` | `CharacterState` (Structured Outputs) | JSONスキーマ準拠を強制 |
| `temperature` | 0.7（初回）→ Temperature Decay | リトライ時に段階的に下げる |
| `max_tokens` | 1024 | 状態JSONは比較的短い |

**Self-Healing:**
```
ValidationError 発生
  ↓
リトライ (最大3回)
  ↓ 3回失敗
フォールバック:
  h_t = h_{t-1}.model_copy(deep=True)
  h_t.memory_buffer.append(f"[Day {t}: フォールバック - イベント「{x_t.description[:50]}」に対する状態更新に失敗]")
  h_t.memory_buffer = h_t.memory_buffer[-3:]  # ウィンドウサイズ維持
```

### 3.2 Phase 2: コンテンツ生成 (Content Generation)

**責務:** 更新された状態 `h_t` とイベント `x_t` に基づき、ブログ日記本文 `D_t` を生成する。

**入力:**
| 項目 | ソース | 形式 |
|---|---|---|
| ペルソナ定義 | `prompts/System_Persona.md` | System Prompt (テキスト) |
| 生成ルール | `prompts/Prompt_Generator.md` | User Prompt (テキスト) |
| 今日の状態 `h_t` | Phase 1の出力 | JSON (`CharacterState`) |
| 今日のイベント `x_t` | `scenario.py` | JSON (`DailyEvent`) |
| 修正指示 (リトライ時) | Phase 3の出力 | テキスト (`revision_instruction`) |

**出力:** Markdown テキスト（プレーンテキスト）

**LLM呼び出し設定:**
| パラメータ | 値 | 理由 |
|---|---|---|
| `response_format` | テキスト (NOT Structured Outputs) | 表現力豊かな自由テキスト生成のため |
| `temperature` | 0.7（初回）→ Temperature Decay | |
| `max_tokens` | 4096 | ブログ記事は長文になりうる |

**重要な設計判断:**
- Phase 2 では Structured Outputs を使わない。JSONエスケープの制約が文学的表現を阻害するため
- 日記本文に含まれるべき要素（感情の言語化ルール、文体）は `Prompt_Generator.md` で指定する

### 3.3 Phase 3: Critic評価 (Critic Evaluation)

**責務:** Actorの出力（`h_t` + `D_t`）を定量評価し、Pass/Rejectを判定する。

**入力:**
| 項目 | ソース | 形式 |
|---|---|---|
| ペルソナ定義 | `prompts/System_Persona.md` | System Prompt (テキスト) |
| 評価基準 | `prompts/Prompt_Critic.md` | User Prompt (テキスト) |
| 今日の状態 `h_t` | Phase 1の出力 | JSON |
| 日記本文 `D_t` | Phase 2の出力 | テキスト |
| 今日のイベント `x_t` | `scenario.py` | JSON |
| 期待変動幅 `expected_delta` | プログラムで算出 | JSON |
| 実際の変動幅 `deviation` | プログラムで算出 | JSON |

**出力:** `CriticScore` (JSON / Structured Outputs)

**Neuro-symbolic 検証ロジック:**

```python
# プログラム側で算出（LLMには依存しない）
def compute_expected_delta(event: DailyEvent) -> dict[str, float]:
    """イベントの emotional_impact から各パラメータの期待変動幅を算出する。"""
    return {
        param: event.emotional_impact * sensitivity
        for param, sensitivity in EMOTION_SENSITIVITY.items()
    }

def compute_deviation(prev: CharacterState, curr: CharacterState, expected: dict[str, float]) -> dict[str, float]:
    """実際の変動と期待変動の乖離を算出する。"""
    return {
        param: (getattr(curr, param) - getattr(prev, param)) - expected_val
        for param, expected_val in expected.items()
    }
```

**判定ロジック:**
```python
def judge(score: CriticScore) -> bool:
    """全スコアが3以上で Pass。"""
    return all(
        getattr(score, field) >= 3
        for field in ["temporal_consistency", "emotional_plausibility", "persona_deviation"]
    )
```

**3層 Critic パイプライン (`CriticPipeline`):**

```
CriticPipeline:
  Layer 1: RuleBasedValidator (決定論的)
    - 文字数レンジチェック (800-2000文字)
    - 禁止表現の検出 (絵文字等)
    - 禁止一人称の検出 (僕/俺/私 等)
    - 前日との重複率チェック (trigram overlap > 30% で減点)
    - 感情パラメータの方向整合性
    - has_critical_failure(): 致命的違反の検出 → Veto権発動

  Layer 2: StatisticalChecker (数値的)
    - 文体統計: 平均文長、句読点頻度、疑問文比率
    - deviation 分析 (期待変動との乖離が大きい場合に減点)
    - 断定文比率 (高インパクト時の過度な断定を検出)

  Layer 3: LLMJudge (定性評価)
    - 従来の Prompt_Critic.md による LLM 評価
    - Layer 1/2 の結果をコンテキストとして注入
    - 逆推定一致チェック: 状態-文章の因果整合性スコア (1-5)
```

**最終スコア算出 (Veto権付き):**
```python
if rule_based_validator.has_critical_failure(result):
    # 致命的違反 → 該当軸にスコア上限キャップ適用
    final_score[axis] = min(weighted_score[axis], veto_cap[axis])
else:
    final_score[axis] = (
        rule_based_score[axis] * 0.3 +
        statistical_score[axis] * 0.2 +
        llm_score[axis] * 0.5
    )
# 逆推定一致スコア <= 2.0 の場合、emotional軸にもveto適用
```

**致命的違反の定義:**
- 禁止一人称の使用 → persona 軸に veto
- 文字数レンジ逸脱 (中央値の ±50% 超) → 全軸に veto
- trigram overlap > 50% → temporal 軸に veto

重みは `config.py` の `CriticWeights`、veto上限は `VetoCaps` で設定可能。

新スキーマ: `LayerScore`, `CriticResult` (+ `inverse_estimation_score`, `veto_applied`), `LLMDeltaResponse`

### 3.3.1 Critic ログ蓄積と軽量フィードバック (`engine/critic_log.py`)

Critic 評価結果をログとして蓄積し、過去の失敗パターンを Actor プロンプトにフィードバックする:

```
CriticLogEntry:
  day: int                      # 経過日数
  scores: CriticResult          # 3層評価結果
  actor_input_summary: str      # Actor入力の要約
  generated_text_hash: str      # 生成テキストのSHA-256ハッシュ
  failure_patterns: list[str]   # Layer1/2で検出された問題パターン
  llm_delta_reason: str         # LLM deltaの変化理由
  inverse_estimation_score: float | None  # 逆推定一致スコア (1-5)
  timestamp: datetime

CriticLog:
  entries: list[CriticLogEntry]
  save(path) -> None            # JSON Lines形式で永続化
  load(path) -> CriticLog       # 既存ログ読み込み
  get_low_score_patterns(axis, threshold, top_k) -> list[str]
  get_all_low_score_patterns(threshold, top_k) -> list[str]
```

**フィードバックフロー:**
1. 各 Day 完了後、`CriticLogEntry` を蓄積
2. 次 Day の生成前に `get_all_low_score_patterns()` で過去の失敗パターンを取得
3. `build_feedback_prompt()` で Actor プロンプトに注入
4. Actor は過去の問題を回避して日記を生成

### 3.4 リトライ制御

```
Phase 2 生成 (temperature=0.7)
  ↓
Phase 3 評価
  ↓ Reject
Phase 2 再生成 (temperature=0.5, revision_instruction 注入)
  ↓
Phase 3 再評価
  ↓ Reject
Phase 2 再生成 (temperature=0.3, revision_instruction 注入)
  ↓
Phase 3 再評価
  ↓ Reject
Best-of-N: 全候補の CriticScore 合計が最大のペア (h_t, D_t) を強制採用
```

**リトライの状態管理:**
```python
@dataclass
class RetryCandidate:
    """リトライ候補を保持する構造体。"""
    attempt: int
    temperature: float
    state: CharacterState
    diary_text: str
    critic_score: CriticScore
    total_score: int  # 3スコアの合計

# Best-of-N 選択
best = max(candidates, key=lambda c: c.total_score)
```

---

## 4. Self-Healing 設計

### 4.1 エラー分類とハンドリング戦略

| エラー種別 | 発生箇所 | 検出方法 | ハンドリング |
|---|---|---|---|
| JSONパースエラー | Phase 1 出力 | `json.JSONDecodeError` | リトライ（最大3回）→ 前日状態コピー |
| Pydanticバリデーションエラー | Phase 1 出力 | `pydantic.ValidationError` | リトライ（最大3回）→ 前日状態コピー |
| 範囲外の感情値 | Phase 1 出力 | カスタムバリデータ | `clamp(-1.0, value, 1.0)` で正規化 |
| memory_buffer 超過 | Phase 1 出力 | `len()` チェック | 末尾3件に切り詰め |
| Critic全スコア不合格 | Phase 3 出力 | `judge()` 関数 | リトライ → Best-of-N |
| API レートリミット | 全Phase | `RateLimitError` | 指数バックオフ（2^n秒、最大60秒） |
| API タイムアウト | 全Phase | `Timeout` | リトライ（最大3回） |
| 予期しない例外 | 全箇所 | `Exception` | ログ記録 + 該当Dayスキップ + 次Dayへ |

### 4.2 フォールバック階層

```
Level 1: リトライ (同一Phase内、最大3回)
  ↓ 失敗
Level 2: Phase固有フォールバック
  - Phase 1: 前日状態コピー + 暫定サマリ
  - Phase 3: Best-of-N 強制採用
  ↓ 失敗
Level 3: Dayスキップ
  - 該当Dayの出力を "[生成失敗]" としてログに記録
  - 前日の状態 h_{t-1} をそのまま h_t として次Dayに引き継ぐ
  ↓ 連続3Day以上失敗
Level 4: パイプライン中断
  - 生成済みのDayの成果物を保存
  - エラーレポートを generation_log.json に出力
  - 非ゼロの終了コードで終了
```

### 4.3 値の正規化

```python
def clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """連続変数を許容範囲にクランプする。"""
    return max(min_val, min(max_val, value))

# Pydantic の field_validator として実装
from pydantic import field_validator

class CharacterState(BaseModel):
    fatigue: float          # -1.0〜1.0
    motivation: float       # -1.0〜1.0
    stress: float           # -1.0〜1.0
    current_focus: str      # 現在の関心事
    unresolved_issue: str | None  # 未解決の課題
    growth_theme: str       # 成長テーマ
    memory_buffer: list[str]  # 過去3日分のサマリ (スライディングウィンドウ)
    relationships: dict[str, float]  # 人物への好感度

    @field_validator("fatigue", "motivation", "stress")
    @classmethod
    def clamp_continuous_vars(cls, v: float) -> float:
        return clamp(v)
```

---

## 5. モジュール設計

### 5.1 モジュール依存関係

```
main.py
  └─▶ engine/pipeline.py
        ├─▶ engine/actor.py
        │     ├─▶ schemas.py (CharacterState, DailyEvent)
        │     └─▶ prompts/ (System_Persona.md, Prompt_StateUpdate.md, Prompt_Generator.md)
        ├─▶ engine/critic.py
        │     ├─▶ schemas.py (CriticScore)
        │     └─▶ prompts/ (System_Persona.md, Prompt_Critic.md)
        └─▶ config.py (EMOTION_SENSITIVITY, リトライ設定)

scenario.py
  └─▶ schemas.py (DailyEvent)

visualization.py (後処理)
  └─▶ output/generation_log.json → output/state_trajectory.png
```

### 5.2 各モジュールの責務

#### `main.py` — エントリポイント
- CLI引数の解析（`--day`, `--output-dir` 等）
- `pipeline.run()` の呼び出し
- 最終的なファイル出力の制御
- 可視化の実行（`visualization.py` の呼び出し）

#### `config.py` — 設定管理
- `EMOTION_SENSITIVITY` の定義
- リトライ上限・Temperature設定
- LLM APIの接続設定（モデル名、エンドポイント）
- 出力ディレクトリパス
- 環境変数からの設定読み込み

```python
# config.py の設計方針
from pydantic_settings import BaseSettings

class CSDGConfig(BaseSettings):
    """環境変数 or .env から読み込む設定。"""

    # LLM設定
    llm_model: str = "gpt-4o"
    llm_api_key: str  # 必須
    llm_base_url: str = "https://api.openai.com/v1"

    # パイプライン設定
    max_retries: int = 3
    initial_temperature: float = 0.7
    temperature_decay_step: float = 0.2
    memory_window_size: int = 3

    # 感情感度係数
    emotion_sensitivity_stress: float = -0.3
    emotion_sensitivity_motivation: float = 0.4
    emotion_sensitivity_fatigue: float = -0.2

    # 出力
    output_dir: str = "output"

    model_config = {"env_prefix": "CSDG_"}

    @property
    def emotion_sensitivity(self) -> dict[str, float]:
        return {
            "stress": self.emotion_sensitivity_stress,
            "motivation": self.emotion_sensitivity_motivation,
            "fatigue": self.emotion_sensitivity_fatigue,
        }

    @property
    def temperature_schedule(self) -> list[float]:
        """リトライ時のTemperatureスケジュールを生成する。"""
        return [
            self.initial_temperature - (self.temperature_decay_step * i)
            for i in range(self.max_retries)
        ]
```

#### `schemas.py` — Pydanticモデル定義
- `DailyEvent` — 日次イベント
- `CharacterState` — キャラクター内部状態（`field_validator` によるクランプ付き）
- `CriticScore` — 評価器スコア
- `GenerationRecord` — 1Dayの生成記録（ログ用）
- `PipelineLog` — パイプライン全体のログ

```python
class GenerationRecord(BaseModel):
    """1Dayの生成記録。generation_log.json の1要素。"""
    day: int
    event: DailyEvent
    initial_state: CharacterState
    final_state: CharacterState
    diary_text: str
    critic_scores: list[CriticScore]  # リトライ含む全スコア
    retry_count: int
    fallback_used: bool
    temperature_used: float
    phase1_duration_ms: int
    phase2_duration_ms: int
    phase3_duration_ms: int
    expected_delta: dict[str, float]   # Neuro-symbolic: 期待変動幅
    actual_delta: dict[str, float]     # 実際の変動幅
    deviation: dict[str, float]        # 期待値との乖離

class PipelineLog(BaseModel):
    """パイプライン全体のログ。"""
    pipeline_version: str = "1.0.0"
    executed_at: datetime
    config_summary: dict[str, object]
    prompt_hashes: dict[str, str]
    records: list[GenerationRecord]
    total_duration_ms: int
    total_api_calls: int
    total_retries: int
    total_fallbacks: int
```

#### `scenario.py` — シナリオ定義
- 7日分の `DailyEvent` のリスト定義
- 初期状態 `h_0` の定義
- シナリオのバリデーション（Day番号の連続性、emotional_impact の範囲）

#### `engine/actor.py` — Actor
- Phase 1: `update_state(prev_state, event, persona, prompt) -> CharacterState`
- Phase 2: `generate_diary(state, event, persona, prompt, revision_instruction?) -> str`
- プロンプトの読み込みとテンプレート展開
- LLM API呼び出しの抽象化

#### `engine/critic.py` — Critic
- Phase 3: `evaluate(state, diary_text, event, expected_delta, deviation, persona, prompt) -> CriticScore`
- `judge(score) -> bool` — Pass/Reject判定
- `compute_expected_delta(event) -> dict`
- `compute_deviation(prev, curr, expected) -> dict`

#### `engine/pipeline.py` — パイプライン制御
- `run(config, scenario, initial_state) -> PipelineLog`
- Day単位のループ制御
- リトライ制御（Temperature Decay + Best-of-N）
- Self-Healing / フォールバック制御
- memory_buffer のスライディングウィンドウ管理
- 生成記録の収集

---

## 6. プロンプトアーキテクチャ

### 6.1 プロンプトの構成と注入順序

各Phaseで構築されるLLMプロンプトは、以下の順序でコンテンツが注入される。

**Phase 1 (State Update):**
```
[System] System_Persona.md
[User]   Prompt_StateUpdate.md
         + "## 前日の状態" + h_{t-1}.model_dump_json()
         + "## 今日のイベント" + x_t.model_dump_json()
         + "## エピソード記憶" + memory_buffer の内容
```

**Phase 2 (Content Generation):**
```
[System] System_Persona.md
[User]   Prompt_Generator.md
         + "## 今日の状態" + h_t.model_dump_json()
         + "## 今日のイベント" + x_t.model_dump_json()
         + "## エピソード記憶" + memory_buffer の内容
         + (リトライ時) "## 修正指示" + revision_instruction
```

**Phase 3 (Critic Evaluation):**
```
[System] System_Persona.md  (※Criticもペルソナを理解する必要がある)
[User]   Prompt_Critic.md
         + "## 評価対象の日記" + D_t
         + "## 今日の状態" + h_t.model_dump_json()
         + "## 今日のイベント" + x_t.model_dump_json()
         + "## 期待変動幅" + expected_delta (JSON)
         + "## 実際の変動幅と乖離" + deviation (JSON)
```

### 6.2 プロンプトのテンプレート展開

プロンプトファイルはMarkdown形式で記述し、動的データの注入にはPythonのテンプレート展開を使用する。

```python
def load_prompt(path: str, **kwargs: str) -> str:
    """プロンプトファイルを読み込み、テンプレート変数を展開する。"""
    template = Path(path).read_text(encoding="utf-8")
    return template.format(**kwargs)
```

**注意:** プロンプトファイル自体にはPythonコードを含めない。`{variable_name}` 形式のプレースホルダのみを使用する。

### 6.3 プロンプトのバージョン管理

- プロンプトファイルはGit管理下に置き、変更履歴を追跡する
- プロンプトの変更は `generation_log.json` にプロンプトのハッシュ値として記録する（再現性担保）
- 大規模なプロンプト変更は `.steering/` に設計記録を残す

---

## 7. 出力・可視化設計

### 7.1 成果物ファイル

`output/day_XX.md` のフォーマット:

```markdown
---
day: 1
date: "生成日時"
event_type: neutral
domain: 仕事
emotional_impact: 0.2
stress: -0.05
motivation: 0.28
fatigue: 0.06
retry_count: 0
fallback_used: false
---

（ブログ本文）
```

YAMLフロントマターにメタデータを埋め込むことで、後処理での分析を容易にする。

### 7.2 実行ログ

`output/generation_log.json` は `PipelineLog` モデルをそのままシリアライズしたもの。
以下の情報が追跡可能:
- 各Dayの全Phase入出力
- リトライ回数と各回のCriticScore
- フォールバック発生の有無
- 各Phaseの処理時間
- API呼び出し総数

### 7.3 状態推移グラフ

`output/state_trajectory.png` は以下を含む2段構成のグラフ:

**上段:** 7日間の感情パラメータ推移
- X軸: Day (1〜7)
- Y軸: パラメータ値 (-1.0〜1.0)
- 3本の折れ線: `stress`（赤）, `motivation`（青）, `fatigue`（灰）
- 各Dayのイベントタイプをマーカー色で表示（positive=緑、negative=赤、neutral=灰）

**下段:** CriticScoreの推移
- X軸: Day (1〜7)
- Y軸: スコア (1〜5)
- 3本の折れ線: `temporal_consistency`, `emotional_plausibility`, `persona_deviation`
- 合格ライン（スコア3）を水平破線で表示

---

## 8. 技術選定

### 8.1 ランタイム・言語

| 項目 | 選定 | 理由 |
|---|---|---|
| 言語 | Python 3.11+ | LLM APIライブラリのエコシステム、Pydantic v2のネイティブサポート |
| パッケージ管理 | uv | pip比で10〜100倍高速、lockfileによる再現性 |

### 8.2 主要ライブラリ

| ライブラリ | バージョン | 用途 | 選定理由 |
|---|---|---|---|
| `pydantic` | v2.x | データバリデーション | Structured Outputs対応、`field_validator` による宣言的制約 |
| `pydantic-settings` | v2.x | 設定管理 | 環境変数・.envの自動読み込み |
| `openai` | v1.x | LLM API | Structured Outputs、response_format対応 |
| `matplotlib` | v3.x | 可視化 | 軽量、依存少、静的グラフ生成に十分 |
| `pytest` | v8.x | テスト | フィクスチャ、パラメタライズ、豊富なプラグイン |
| `ruff` | latest | リンター/フォーマッター | 高速、flake8+isort+blackを統合 |
| `mypy` | latest | 型チェック | strict modeでPydanticモデルの整合性を静的検証 |

### 8.3 LLM API選択の抽象化

将来的にOpenAI以外のLLM（Anthropic Claude等）に切り替える可能性を考慮し、LLM呼び出しを抽象化する。

```python
from abc import ABC, abstractmethod

class LLMClient(ABC):
    """LLM API呼び出しの抽象インターフェース。"""

    @abstractmethod
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        """Structured Outputs による構造化生成。"""
        ...

    @abstractmethod
    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """プレーンテキスト生成。"""
        ...

class OpenAIClient(LLMClient):
    """OpenAI API実装。"""
    ...

class AnthropicClient(LLMClient):
    """Anthropic API実装（将来対応）。"""
    ...
```

---

## 9. 非機能要件

### 9.1 パフォーマンス

| 指標 | 目標値 | 備考 |
|---|---|---|
| 1Day あたりの処理時間 | 60秒以内（リトライなし） | API応答時間に依存 |
| パイプライン全体 | 10分以内 | 7Day × (最大3リトライ) |
| メモリ使用量 | 512MB以内 | matplotlib のグラフ生成含む |

### 9.2 再現性

- `generation_log.json` に全入出力を記録し、同一入力・同一プロンプトでの再実行を可能にする
- ただし、LLMの出力は非決定的であるため、完全な再現性は保証しない
- シード値（`seed` パラメータ）を設定に含め、可能な範囲で再現性を確保する

### 9.3 可観測性

- 全Phaseの入出力をログに記録する
- エラー発生時はスタックトレースを `generation_log.json` に含める
- 処理時間をPhase単位で計測する
- API呼び出し回数をカウントする（コスト管理）

### 9.4 セキュリティ

- API キーは環境変数 (`CSDG_LLM_API_KEY`) で管理し、コードにハードコードしない
- `.env` ファイルは `.gitignore` に追加する
- 生成ログにAPI キーが含まれないよう、出力前にサニタイズする

---

## 10. 将来の拡張ポイント

以下は現時点では実装しないが、アーキテクチャ上考慮しておく拡張ポイントである。

| 拡張 | 概要 | アーキテクチャ上の対応 |
|---|---|---|
| マルチキャラクター | 複数のキャラクターが同一世界で日記を書く | `CharacterState` にキャラクターIDを追加、`scenario.py` をキャラクター別に分離 |
| 動的シナリオ | イベントを事前定義ではなくLLMで動的生成 | `scenario.py` を `ScenarioGenerator` クラスに置換 |
| Web UI | ブラウザ上で日記を閲覧・パラメータ調整 | FastAPI + React構成。パイプラインをAPIとして公開 |
| ストリーミング出力 | 日記生成をリアルタイムで表示 | LLM APIのストリーミングレスポンス + SSE |
| 評価指標の拡張 | CriticScoreに新しい評価軸を追加 | `CriticScore` モデルにフィールド追加 + `Prompt_Critic.md` 更新 |
| LLMプロバイダの切替 | OpenAI以外のLLMを使用 | `LLMClient` 抽象クラスの新規実装を追加 |
