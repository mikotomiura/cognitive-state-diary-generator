# CSDG MVP 実装ワークフロー

> **目的:** Claude Code を使って CSDG（Cognitive-State Diary Generator）の MVP を段階的に実装するための完全なワークフロードキュメント。
> 各 Phase に「Claude Code へ投げかける具体的なプロンプト」を含む。
> Phase 0 から Phase 9 まで順番に実行すること。
尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 

---

## 全体マップ

```
Phase 0: プロジェクト初期セットアップ     ← 土台
Phase 1: データモデル (schemas.py)        ← 最下層モジュール
Phase 2: シナリオ定義 (scenario.py)       ← 入力データ
Phase 3: 設定管理 (config.py)             ← 環境変数・ハイパーパラメータ
Phase 4: プロンプトファイル (prompts/)     ← LLMへの指示
Phase 5: LLMクライアント (llm_client.py)  ← API抽象化
Phase 6: Actor (actor.py)                 ← Phase 1 & 2 の生成
Phase 7: Critic (critic.py)               ← Phase 3 の評価
Phase 8: パイプライン (pipeline.py)       ← ループ・リトライ・フォールバック
Phase 9: エントリポイント & 可視化        ← main.py + visualization.py
```

**依存関係:** 各Phaseは前のPhaseの成果物に依存する。スキップ不可。

---

## Phase 0: プロジェクト初期セットアップ

### 目的
リポジトリの骨格を作り、開発に必要な環境を整える。

### Claude Code プロンプト

```
以下の指示に従って、CSDG プロジェクトの初期セットアップを行ってください。

## 前提
- リポジトリ: https://github.com/mikotomiura/cognitive-State-Diary-generator.git
- Python 3.11+
- パッケージマネージャ: uv

## 作業内容

### 1. ディレクトリ構造の作成
以下のディレクトリを作成してください:
- csdg/
- csdg/engine/
- prompts/
- tests/
- tests/fixtures/
- output/
- docs/
- .steering/

各 Python パッケージディレクトリに __init__.py を作成してください。
csdg/__init__.py には __version__ = "0.1.0" を定義してください。

### 2. pyproject.toml の作成
以下の内容で作成してください:
- プロジェクト名: csdg
- Python要件: >=3.11
- 依存関係:
  - pydantic>=2.0
  - pydantic-settings>=2.0
  - anthropic>=0.30
  - matplotlib>=3.0
- 開発用依存関係 ([project.optional-dependencies] dev):
  - pytest>=8.0
  - pytest-asyncio>=0.23
  - pytest-cov>=5.0
  - mypy>=1.10
  - ruff>=0.5
- [tool.ruff] の設定:
  - target-version = "py311"
  - line-length = 120
  - select = ["E", "W", "F", "I", "N", "UP", "B", "SIM", "TCH", "RUF"]
- [tool.mypy] の設定:
  - python_version = "3.11"
  - strict = true
  - plugins = ["pydantic.mypy"]
- [tool.pytest.ini_options] の設定:
  - testpaths = ["tests"]
  - asyncio_mode = "auto"
  - markers に e2e マーカーを定義

### 3. .env.example の作成
以下の環境変数テンプレートを作成:
- CSDG_LLM_PROVIDER=anthropic
- CSDG_ANTHROPIC_API_KEY=your-anthropic-api-key-here
- CSDG_ANTHROPIC_MODEL=claude-sonnet-4-20250514
- CSDG_GEMINI_API_KEY=your-gemini-api-key-here
- CSDG_GEMINI_MODEL=gemini-2.0-flash
- CSDG_MAX_RETRIES=3
- CSDG_INITIAL_TEMPERATURE=0.7
- CSDG_OUTPUT_DIR=output
- CSDG_EMOTION_SENSITIVITY_STRESS=-0.3
- CSDG_EMOTION_SENSITIVITY_MOTIVATION=0.4
- CSDG_EMOTION_SENSITIVITY_FATIGUE=-0.2

### 4. .gitignore の作成
.env, output/, __pycache__/, .mypy_cache/, .ruff_cache/,
.pytest_cache/, .venv/, .uv/, .DS_Store を除外

### 5. .python-version の作成
3.11 を記述

### 6. .steering/[今日の日付]-project-setup/ の作成
requirement.md, design.md, tasklist.md を作成し、
このセットアップ作業の記録を残してください。

## 参照ドキュメント
以下のドキュメントを読み、設計方針に従ってください:
- CLAUDE.md
- docs/repository-structure.md

## 完了条件
- ディレクトリ構造が docs/repository-structure.md と一致している
- pyproject.toml が正しく記述されている
- uv sync が成功する
```

### 完了チェック
- [ ] ディレクトリ構造が作成されている
- [ ] `pyproject.toml` が正しい
- [ ] `.env.example` が作成されている
- [ ] `.gitignore` が作成されている
- [ ] `uv sync` が成功する

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 1: データモデル (schemas.py)

### 目的
システム全体の基盤となる Pydantic モデルを定義する。他の全モジュールがこれに依存する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/schemas.py を実装してください。

## 前提
- docs/architecture.md の「§2. 状態管理アーキテクチャ」と「§3. パイプライン詳細設計」を読んでください
- docs/glossary.md の「§2. データモデル用語」を読んでください
- .claude/skills/pydantic-patterns/SKILL.md を読んでください

## 実装するモデル

### 1. DailyEvent（日次イベント）
- day: int — 経過日数 (1-7)
- event_type: str — "positive" / "negative" / "neutral" のいずれか
- domain: str — 空文字列でないこと
- description: str — 10文字以上であること
- emotional_impact: float — -1.0〜1.0 の範囲（範囲外は ValidationError）
- model_config = {"frozen": True} でイミュータブルにする
- field_validator で event_type, description, emotional_impact をバリデーション

### 2. CharacterState（キャラクター内部状態）
- fatigue: float — 疲労度 (0.0〜1.0)。範囲外はクランプ（エラーにしない）
- motivation: float — モチベーション (-1.0〜1.0)。同上
- stress: float — ストレス値 (-1.0〜1.0)。同上
- current_focus: str
- unresolved_issue: str | None = None
- growth_theme: str
- memory_buffer: list[str] = Field(default_factory=list) — 最大3件に自動制限
- relationships: dict[str, float] = Field(default_factory=dict)
- field_validator で連続変数のクランプ、memory_buffer のサイズ制限を実装

### 3. CriticScore（評価器スコア）
- temporal_consistency: int — 1〜5（範囲外は ValidationError）
- emotional_plausibility: int — 1〜5
- persona_deviation: int — 1〜5
- hook_strength: float — 0.0〜1.0（診断専用、Pass/Reject判定には不使用、default=0.0）
- reject_reason: str | None = None
- revision_instruction: str | None = None
- model_validator で「Reject時は reject_reason と revision_instruction が必須」を検証

### 4. GenerationRecord（1Dayの生成記録）
- day, event, initial_state, final_state, diary_text
- critic_scores: list[CriticScore]
- retry_count, fallback_used, temperature_used
- phase1_duration_ms, phase2_duration_ms, phase3_duration_ms
- expected_delta, actual_delta, deviation (各 dict[str, float])

### 5. PipelineLog（パイプライン全体ログ）
- pipeline_version: str = "1.0.0"
- executed_at: datetime
- config_summary: dict[str, object]
- prompt_hashes: dict[str, str]
- records: list[GenerationRecord]
- total_duration_ms, total_api_calls, total_retries, total_fallbacks

## 規約
- すべてのフィールドに Field(description="...") を付ける
- Google style docstring を各クラスに記述する
- 型アノテーションは X | None 構文を使用する
- .claude/skills/pydantic-patterns/validation-recipes.md のパターンに従う

## テスト
tests/test_schemas.py も同時に作成してください:
- CharacterState のクランプテスト（上限、下限、範囲内）
- CharacterState の memory_buffer サイズ制限テスト
- DailyEvent の event_type バリデーションテスト
- DailyEvent の emotional_impact 範囲テスト
- CriticScore のスコア範囲テスト
- CriticScore の Reject 時の必須フィールドテスト
- JSON 往復変換テスト（model_dump_json → model_validate_json）
- パラメタライズを活用して境界値を網羅する
- .claude/skills/test-standards/SKILL.md に従う

## 完了条件
- pytest tests/test_schemas.py -v が全件 Pass
- mypy csdg/schemas.py --strict がエラー 0
- ruff check csdg/schemas.py がエラー 0
```

### 完了チェック
- [ ] 5つのモデルが定義されている
- [ ] 全フィールドに `Field(description=...)` がある
- [ ] `field_validator` でクランプ・バリデーションが実装されている
- [ ] テストが全件 Pass
- [ ] mypy, ruff がエラー 0

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 2: シナリオ定義 (scenario.py)
already.

### 目的
7日分の DailyEvent と初期状態 h_0 を定義する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/scenario.py を実装してください。

## 前提
- docs/functional-design.md の「§8. シナリオ仕様」を読んでください
- docs/glossary.md の「§6. シナリオ・物語用語」と「§7. キャラクター用語」を読んでください
- csdg/schemas.py の DailyEvent と CharacterState の定義を確認してください

## 実装内容

### 1. 7日分の DailyEvent リスト (SCENARIO)

docs/functional-design.md §8.2 の感情パラメータ想定推移テーブルに基づき、
以下の7日分のイベントを定義してください:

- Day 1: neutral / 仕事 / impact=-0.15 — 自動化スクリプト完成、空虚感
- Day 2: positive / 趣味 / impact=+0.5 — 古書店で岡倉天心『茶の本』初版を発見
- Day 3: negative / 仕事 / impact=-0.4 — コードレビューで「動くけど読めない」と指摘
- Day 4: negative / 内省 / impact=-0.8 — 深夜の過去ブログ遡り、過去の自分との対峙
- Day 5: positive / 人間関係 / impact=+0.3 — ミナとの偶然の再会、「ブログに書いたら」
- Day 6: positive / 仕事 / impact=+0.35 — ラムダ式を関数に書き直し、『茶の本』の一節
- Day 7: positive / 思想 / impact=+0.25 — カフェで1週間の振り返り、問いの継続

各イベントの description は、アーキテクチャ文書のシナリオ設計セクションの
記述を参考に、客観的な出来事として10文字以上で記述してください。

### 2. 初期状態 (INITIAL_STATE)

CharacterState の初期インスタンスを定義:
- fatigue=0.1, motivation=0.2, stress=-0.1
- current_focus="来週の社内コードレビュー会の準備"
- unresolved_issue=None
- growth_theme="「考えること」と「生きること」の折り合い"
- memory_buffer=[]
- relationships={"深森那由他": 0.6, "ミナ": 0.4}

### 3. バリデーション関数

def validate_scenario(events: list[DailyEvent]) -> None:
  - day が 1 から連番であること
  - 全イベントの Pydantic バリデーションが通ること
  - emotional_impact が範囲内であること

## テスト
tests/test_scenario.py を作成:
- SCENARIO の件数が7であること
- day が 1〜7 の連番であること
- 全イベントの event_type が有効であること
- emotional_impact が範囲内であること
- Day 4 の emotional_impact が -0.9 であること（ストレステスト確認）
- INITIAL_STATE の初期値が正しいこと
- validate_scenario が正常系で例外を出さないこと
- validate_scenario が異常系（day欠番等）で ValueError を出すこと

## 完了条件
- pytest tests/test_scenario.py -v が全件 Pass
- mypy, ruff がエラー 0
```

### 完了チェック
- [ ] 7日分のイベントが定義されている
- [ ] 初期状態が定義されている
- [ ] バリデーション関数が実装されている
- [ ] テストが全件 Pass
尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 3: 設定管理 (config.py)
finish
### 目的
環境変数・.env からの設定読み込みを一元管理する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/config.py を実装してください。

## 前提
- docs/architecture.md の「§5.2 各モジュールの責務 — config.py」を読んでください
- docs/functional-design.md の「§5.4 環境変数」を読んでください

## 実装内容

pydantic-settings の BaseSettings を使用して CSDGConfig クラスを実装:

class CSDGConfig(BaseSettings):
    # LLM設定
    llm_provider: str = "anthropic"  # "anthropic" or "gemini"
    anthropic_api_key: str  # Anthropic利用時に必須
    gemini_api_key: str  # Gemini利用時に必須
    llm_model: str = "claude-sonnet-4-20250514"
    llm_base_url: str = "https://api.anthropic.com"

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

    # プロパティ:
    # emotion_sensitivity -> dict[str, float] を返す
    # temperature_schedule -> list[float] を返す（リトライ時のスケジュール）

## テスト
tests/test_config.py を作成:
- デフォルト値が正しいこと（APIキー以外）
- emotion_sensitivity プロパティが正しい dict を返すこと
- temperature_schedule が [0.7, 0.5, 0.3] を返すこと（max_retries=3 の場合）
- 環境変数から値を読み込めること（monkeypatch 使用）

## 完了条件
- pytest tests/test_config.py -v が全件 Pass
- mypy, ruff がエラー 0
```

### 完了チェック
- [ ] `CSDGConfig` が定義されている
- [ ] `emotion_sensitivity` プロパティが動作する
- [ ] `temperature_schedule` プロパティが動作する
- [ ] テストが全件 Pass

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 4: プロンプトファイル (prompts/)
finish.
### 目的
4つのプロンプトファイルを作成する。LLMへの指示の核心部分。

### Claude Code プロンプト

```
以下の指示に従って、prompts/ ディレクトリに4つのプロンプトファイルを作成してください。

## 前提
- .claude/skills/prompt-engineering/SKILL.md を読んでください
- .claude/skills/prompt-engineering/examples.md を読んでください
- docs/glossary.md のキャラクター用語セクションを読んでください
- docs/functional-design.md の「§7. ペルソナ仕様」を読んでください

## 作成するファイル

### 1. prompts/System_Persona.md
キャラクター「三浦とこみ」の不変ルールを定義。全 Phase の System Prompt として使用。
以下を含めること:
- 基本プロフィール（26歳、哲学科中退、バックエンドエンジニア）
- 性格の核（「万物を哲学的に捕らえようとするが、感情が先に暴走する」）
- 口調ルール（壮大な比喩、感情爆発時の短文連打、古今接続、自己ツッコミ、「......」）
  → 各ルールに良い例と悪い例を1つずつ含める
- 絶対的禁則事項（絵文字禁止、見下し禁止、断定禁止、正解化禁止）
  → 「こう書いてはいけない」例を各禁則に含める
- 人間関係（深森那由他、ミナ）の説明
- ブログを書く理由

### 2. prompts/Prompt_StateUpdate.md
Phase 1（状態遷移）の User Prompt。
プレースホルダ: {previous_state}, {event}, {memory_buffer}
以下を含めること:
- 連続変数の更新ルール（EMOTION_SENSITIVITY に基づく変動の目安）
- 離散変数の更新ルール
- memory_buffer の更新ルール
- relationships の更新ルール
- 過去との整合性の指示
- 出力形式の指示（CharacterState スキーマの JSON）

### 3. prompts/Prompt_Generator.md
Phase 2（日記生成）の User Prompt。
プレースホルダ: {current_state}, {event}, {memory_buffer}, {revision_instruction}
以下を含めること:
- 日記の構成（冒頭→展開→内省→余韻）
- emotional_impact の大きさに応じた文体の変化指示
- memory_buffer への自然な言及方法
- 分量目安（350〜450文字、タイトル除く）
- 出力形式の指示（Markdownテキスト、JSONではない）
- {revision_instruction} セクション（リトライ時のみ表示、空文字の場合は無視）

### 4. prompts/Prompt_Critic.md
Phase 3（評価）の User Prompt。
プレースホルダ: {diary_text}, {current_state}, {event}, {expected_delta}, {deviation}
以下を含めること:
- 3つの評価軸の1〜5スコア定義（docs/functional-design.md §9.1 の採点基準を転記）
- 「3が合格ライン」の明示
- Reject 時の reject_reason と revision_instruction の出力指示
- expected_delta と deviation の使い方の説明
- 出力形式の指示（CriticScore スキーマの JSON）

## 規約
- プロンプト内の用語は glossary.md に定義されたものを使用する
- プレースホルダは {variable_name} 形式で統一する
- Python コードをプロンプト内に埋め込まない

## 完了条件
- 4つのプロンプトファイルが prompts/ に存在する
- 各ファイルのプレースホルダが docs/architecture.md §6.1 の注入順序と一致している
- ペルソナの禁則事項に「悪い例」が含まれている
- Critic の採点基準が5段階で具体的に記述されている
```

### 完了チェック
- [ ] 4ファイルが `prompts/` に存在する
- [ ] プレースホルダ名が統一されている
- [ ] ペルソナに良い例・悪い例がある
- [ ] Critic の採点基準が5段階で定義されている

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 5: LLMクライアント (llm_client.py)
finish
### 目的
LLM API 呼び出しを抽象化し、将来的なプロバイダ切替に備える。

### Claude Code プロンプト

```
以下の指示に従って、csdg/engine/llm_client.py を実装してください。

## 前提
- docs/architecture.md の「§8.3 LLM API選択の抽象化」を読んでください
- .claude/skills/python-standards/SKILL.md を読んでください

## 実装内容

### 1. 抽象基底クラス: LLMClient

from abc import ABC, abstractmethod

class LLMClient(ABC):
    """LLM API 呼び出しの抽象インターフェース。"""

    @abstractmethod
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        """Structured Outputs による構造化生成。Phase 1, 3 で使用。"""
        ...

    @abstractmethod
    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 512,
    ) -> str:
        """プレーンテキスト生成。Phase 2 で使用。"""
        ...

### 2. Anthropic 実装: AnthropicClient

class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        ...

    async def generate_structured(...) -> BaseModel:
        - anthropic の AsyncAnthropic クライアントを使用
        - response_format に Pydantic モデルを指定（Structured Outputs）
        - レスポンスを response_model.model_validate_json() でパース
        - API エラー時は anthropic の例外をそのまま raise

    async def generate_text(...) -> str:
        - anthropic の AsyncAnthropic クライアントを使用
        - response_format は指定しない（テキスト生成）
        - レスポンスの content を文字列として返す
        - 空文字列の場合は ValueError を raise

## 規約
- すべてに型アノテーション
- Google style docstring
- logging モジュールでリクエスト/レスポンスのメタ情報（トークン数等）をDEBUGログに記録
- APIキーをログに出力しない

## テストについて
LLMClient は抽象クラスなので、テストは Phase 6 (Actor) と Phase 7 (Critic) で
モックを使って間接的にテストします。
ただし、AnthropicClient のインスタンス化が正常にできることの簡単なテストは書いてください。

## 完了条件
- mypy csdg/engine/llm_client.py --strict がエラー 0
- ruff check がエラー 0
```

### 完了チェック
- [ ] `LLMClient` 抽象クラスが定義されている
- [ ] `AnthropicClient` が実装されている
- [ ] mypy, ruff がエラー 0

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 6: Actor (actor.py)
finish
### 目的
Phase 1（状態遷移）と Phase 2（日記生成）を担当する Actor を実装する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/engine/actor.py を実装してください。

## 前提
- docs/architecture.md の「§3.1 Phase 1」「§3.2 Phase 2」「§6. プロンプトアーキテクチャ」を読んでください
- csdg/schemas.py, csdg/engine/llm_client.py, csdg/config.py を読んでください
- .claude/skills/python-standards/examples.md を読んでください

## 実装内容

class Actor:
    """Phase 1（状態遷移）と Phase 2（日記生成）を担当する。"""

    def __init__(self, client: LLMClient, config: CSDGConfig) -> None:
        self._client = client
        self._config = config

    async def update_state(
        self,
        prev_state: CharacterState,
        event: DailyEvent,
    ) -> CharacterState:
        """Phase 1: イベントに基づきキャラクターの内部状態を更新する。

        1. System_Persona.md を System Prompt として読み込む
        2. Prompt_StateUpdate.md をテンプレート展開する
           - {previous_state}: prev_state.model_dump_json(indent=2)
           - {event}: event.model_dump_json(indent=2)
           - {memory_buffer}: "\n".join(prev_state.memory_buffer) or "(記憶なし)"
        3. LLMClient.generate_structured() で CharacterState を生成
        4. 生成された CharacterState を返す（クランプは Pydantic が自動処理）
        """

    async def generate_diary(
        self,
        state: CharacterState,
        event: DailyEvent,
        revision_instruction: str | None = None,
    ) -> str:
        """Phase 2: 更新された状態に基づきブログ日記本文を生成する。

        1. System_Persona.md を System Prompt として読み込む
        2. Prompt_Generator.md をテンプレート展開する
           - {current_state}: state.model_dump_json(indent=2)
           - {event}: event.model_dump_json(indent=2)
           - {memory_buffer}: "\n".join(state.memory_buffer) or "(記憶なし)"
           - {revision_instruction}: "## 修正指示\n" + instruction or ""
        3. LLMClient.generate_text() で日記テキストを生成
        4. 空文字列でないことを確認して返す
        """

    def _load_prompt(self, filename: str) -> str:
        """prompts/ ディレクトリからプロンプトファイルを読み込む。"""

    def _build_state_update_prompt(self, prev_state: CharacterState, event: DailyEvent) -> str:
        """Phase 1 用の User Prompt を構築する。"""

    def _build_generator_prompt(
        self, state: CharacterState, event: DailyEvent, revision: str | None
    ) -> str:
        """Phase 2 用の User Prompt を構築する。"""

## テスト
tests/test_actor.py を作成:
- LLMClient をモックし、update_state が CharacterState を返すことを確認
- LLMClient をモックし、generate_diary が文字列を返すことを確認
- revision_instruction が None の場合と文字列の場合でプロンプトが正しく構築されること
- プロンプトファイルが見つからない場合に FileNotFoundError が発生すること
- conftest.py に mock_llm_client フィクスチャを追加
  (.claude/skills/test-standards/fixture-patterns.md を参照)

## 完了条件
- pytest tests/test_actor.py -v が全件 Pass
- mypy, ruff がエラー 0
- プロンプトファイルを直接 import せず、ファイルから読み込んでいること
```

### 完了チェック
- [ ] `update_state` と `generate_diary` が実装されている
- [ ] プロンプトを外部ファイルから読み込んでいる
- [ ] テストが全件 Pass

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 7: Critic (critic.py)
finish
### 目的
Phase 3（評価）を担当する Critic と、定量検証ロジックを実装する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/engine/critic.py を実装してください。

## 前提
- docs/architecture.md の「§3.3 Phase 3」を読んでください
- docs/functional-design.md の「§9. 品質基準」を読んでください
- docs/glossary.md の「§4. 品質管理・リトライ用語」を読んでください
- csdg/schemas.py, csdg/engine/llm_client.py, csdg/config.py を読んでください

## 実装内容

### 1. 定量検証関数（LLMに依存しない純粋関数）

def compute_expected_delta(
    event: DailyEvent,
    sensitivity: dict[str, float],
) -> dict[str, float]:
    """イベントの emotional_impact から各パラメータの期待変動幅を算出する。

    例: impact=0.6, sensitivity={"stress": -0.3} → {"stress": -0.18}
    """

def compute_deviation(
    prev_state: CharacterState,
    curr_state: CharacterState,
    expected_delta: dict[str, float],
) -> dict[str, float]:
    """実際の変動と期待変動の乖離を算出する。

    actual_delta = curr.param - prev.param
    deviation = actual_delta - expected_delta
    """

def judge(score: CriticScore) -> bool:
    """全スコアが3以上で True（Pass）。1つでも3未満で False（Reject）。"""

### 2. Critic クラス

class Critic:
    """Phase 3（評価）を担当する。"""

    def __init__(self, client: LLMClient, config: CSDGConfig) -> None:
        ...

    async def evaluate(
        self,
        prev_state: CharacterState,
        curr_state: CharacterState,
        diary_text: str,
        event: DailyEvent,
    ) -> CriticScore:
        """日記テキストと状態を評価し、CriticScore を返す。

        1. expected_delta を compute_expected_delta() で算出
        2. deviation を compute_deviation() で算出
        3. System_Persona.md を System Prompt として読み込む
        4. Prompt_Critic.md をテンプレート展開する
           - {diary_text}, {current_state}, {event}, {expected_delta}, {deviation}
        5. LLMClient.generate_structured() で CriticScore を生成
        6. CriticScore を返す
        """

    def _load_prompt(self, filename: str) -> str:
        ...

    def _build_critic_prompt(self, ...) -> str:
        ...

## テスト
tests/test_critic.py を作成:

### 純粋関数のテスト（LLMモック不要）
- compute_expected_delta: positive イベント (impact=+0.6) の各パラメータ計算
- compute_expected_delta: negative イベント (impact=-0.9, Day 4) の計算
- compute_expected_delta: neutral イベント (impact=0.0) で全パラメータ 0.0
- compute_deviation: 期待通りの変動で deviation が 0 に近い
- compute_deviation: 大きな乖離がある場合
- judge: 全スコア 3 以上 → True
- judge: 全スコア ちょうど 3 → True（境界値）
- judge: 1つが 2 → False
- judge: 各スコアが個別に 3 未満の場合（パラメタライズ）

### Critic クラスのテスト（LLMモック使用）
- evaluate が CriticScore を返すこと
- evaluate の返す CriticScore に expected_delta と deviation が反映されていること
  （Criticのプロンプトに注入されていること — プロンプト構築メソッドの戻り値を確認）

## 完了条件
- pytest tests/test_critic.py -v が全件 Pass
- mypy, ruff がエラー 0
- compute_expected_delta, compute_deviation, judge は LLM に依存していないこと
```

### 完了チェック
- [ ] 3つの純粋関数が実装されている
- [ ] `Critic.evaluate` が実装されている
- [ ] 純粋関数のテストが網羅的
- [ ] テストが全件 Pass

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 8: パイプライン (pipeline.py)
finish
### 目的
Day単位のループ、リトライ制御、Self-Healing、memory_buffer管理を統合するパイプラインを実装する。

### Claude Code プロンプト

```
以下の指示に従って、csdg/engine/pipeline.py を実装してください。
これはシステム全体の心臓部です。

## 前提
- docs/architecture.md の「§3.4 リトライ制御」「§4. Self-Healing 設計」を読んでください
- docs/functional-design.md の「§3. 機能要件」F-04（リトライ）、F-05（メモリ管理）、F-08（エラーハンドリング）を読んでください
- csdg/engine/actor.py, csdg/engine/critic.py, csdg/schemas.py, csdg/config.py を読んでください

## 実装内容

import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RetryCandidate:
    """リトライ候補を保持する。"""
    attempt: int
    temperature: float
    state: CharacterState
    diary_text: str
    critic_score: CriticScore
    total_score: int  # 3スコアの合計

class PipelineRunner:
    """3フェーズパイプラインの実行を制御する。"""

    def __init__(self, config: CSDGConfig, actor: Actor, critic: Critic) -> None:
        ...

    async def run(
        self,
        events: list[DailyEvent],
        initial_state: CharacterState,
    ) -> PipelineLog:
        """全Dayのパイプラインを実行する。

        1. Day 1 から順に run_single_day() を呼び出す
        2. 各Day完了後に memory_buffer を更新（スライディングウィンドウ）
        3. 連続3Day以上失敗したら中断
        4. PipelineLog を返す
        """

    async def run_single_day(
        self,
        event: DailyEvent,
        prev_state: CharacterState,
        day: int,
    ) -> GenerationRecord:
        """1Dayのパイプラインを実行する。

        Phase 1: 状態遷移
          - Actor.update_state() を呼び出す
          - ValidationError → 最大3回リトライ → フォールバック（前日状態コピー）

        Phase 2 + Phase 3: 生成 → 評価 → リトライループ
          - Actor.generate_diary() → Critic.evaluate() → judge()
          - Pass → 採用
          - Reject → revision_instruction を注入して Phase 2 から再実行
          - Temperature Decay: config.temperature_schedule に従う
          - 最大リトライ回数超過 → Best-of-N（最高スコアの候補を強制採用）

        処理時間を計測し、GenerationRecord を返す
        """

    def _update_memory_buffer(
        self,
        state: CharacterState,
        diary_text: str,
        day: int,
    ) -> CharacterState:
        """memory_buffer に当日の要約を追加し、ウィンドウサイズを維持する。

        要約は diary_text の先頭100文字 + "..." とする（MVP簡易実装）。
        将来的にはLLMで要約を生成する。
        """

    def _create_fallback_state(
        self,
        prev_state: CharacterState,
        day: int,
        event: DailyEvent,
    ) -> CharacterState:
        """Phase 1 フォールバック: 前日の状態をコピーし暫定サマリを挿入する。"""

    def _select_best_candidate(self, candidates: list[RetryCandidate]) -> RetryCandidate:
        """Best-of-N: 全候補から CriticScore 合計値が最大のものを選択する。"""

## ログ出力
以下のフォーマットで INFO ログを出力すること:
- [Day X] Phase 1: State Update ... OK (X.Xs)
- [Day X] Phase 2: Content Generation ... OK (X.Xs)
- [Day X] Phase 3: Critic Evaluation ... Pass (score: X/X/X) (X.Xs)
- [Day X] Phase 3: Critic Evaluation ... Reject (score: X/X/X) → Retry X/X
- [Day X] Fallback: Phase 1 前日状態コピー
- [Day X] Fallback: Best-of-N (score: X)
- [CSDG] Pipeline complete (X/X days, X retries, X fallbacks)

## テスト
tests/test_pipeline.py を作成:
- 正常系: 全7Day が1回で Pass（モック）
- リトライ: Phase 3 で Reject → リトライで Pass
- Temperature Decay: リトライ時に temperature が減衰していること
- Best-of-N: 3回 Reject → 最高スコア候補が選択される
- Phase 1 フォールバック: ValidationError 3回 → 前日状態コピー
- memory_buffer: Day 5 で buffer が [Day2要約, Day3要約, Day4要約] になること
- Dayスキップ: 予期しない例外 → 該当Day がスキップされ次Day が実行される
- パイプライン中断: 連続3Day失敗 → 中断、生成済み成果物が PipelineLog に含まれる

## 完了条件
- pytest tests/test_pipeline.py -v が全件 Pass
- mypy, ruff がエラー 0
- リトライ・フォールバック・Best-of-N の全パターンがテストされている
```

### 完了チェック
- [ ] `run` と `run_single_day` が実装されている
- [ ] リトライ制御（Temperature Decay + Best-of-N）が動作する
- [ ] Phase 1 フォールバックが動作する
- [ ] memory_buffer のスライディングウィンドウが動作する
- [ ] テストが全件 Pass

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## Phase 9: エントリポイント & 可視化
finish
### 目的
CLIエントリポイント（main.py）と状態推移グラフ（visualization.py）を実装し、パイプライン全体を動作可能にする。

### Claude Code プロンプト

```
以下の指示に従って、csdg/main.py と csdg/visualization.py を実装してください。

## 前提
- docs/functional-design.md の「§4. CLIインターフェース仕様」「§6. 出力仕様」を読んでください
- docs/architecture.md の「§7. 出力・可視化設計」を読んでください
- csdg/engine/pipeline.py, csdg/config.py, csdg/scenario.py を読んでください

## 実装内容

### 1. csdg/main.py

import argparse
import asyncio
import logging

def parse_args() -> argparse.Namespace:
    """CLI引数を解析する。

    オプション:
    --day: int (特定Dayのみ実行)
    --output-dir: str (デフォルト: output)
    --verbose: flag (詳細ログ)
    --skip-visualization: flag (グラフ生成スキップ)
    --dry-run: flag (API呼び出しなしの構成確認)
    """

async def run_pipeline(args: argparse.Namespace) -> None:
    """パイプラインを実行する。

    1. CSDGConfig を読み込む
    2. プロンプトファイルの存在を確認（なければ終了コード 3）
    3. AnthropicClient を生成
    4. Actor, Critic を生成
    5. PipelineRunner を生成
    6. scenario.SCENARIO と scenario.INITIAL_STATE でパイプラインを実行
    7. 各 Day の日記を output/day_XX.md に保存（YAMLフロントマター付き）
    8. generation_log.json を保存
    9. visualization.py でグラフを生成（--skip-visualization でなければ）
    """

def save_diary(record: GenerationRecord, output_dir: str) -> None:
    """日記を YAML フロントマター付き Markdown として保存する。

    ファイル名: day_XX.md (2桁ゼロ埋め)
    フロントマター: day, generated_at, event_type, domain, emotional_impact,
                    state (fatigue, motivation, stress, current_focus, growth_theme),
                    critic_score, retry_count, fallback_used
    """

def main() -> None:
    """エントリポイント。"""
    args = parse_args()
    # ログ設定
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    # 実行
    asyncio.run(run_pipeline(args))

if __name__ == "__main__":
    main()

### 2. csdg/visualization.py

import matplotlib
matplotlib.use("Agg")  # GUIなし環境対応
import matplotlib.pyplot as plt

def generate_state_trajectory(
    log: PipelineLog,
    output_path: str = "output/state_trajectory.png",
) -> None:
    """7日間の感情パラメータ推移と CriticScore の推移グラフを生成する。

    2段構成 (figsize=(12, 8)):
    - 上段: stress(赤), motivation(青), fatigue(灰) の折れ線グラフ
      - X軸: Day (1〜7)
      - Y軸: -1.0〜1.0
      - 各Dayのイベントタイプをマーカー色で表示
    - 下段: temporal_consistency, emotional_plausibility, persona_deviation の折れ線 (hook_strength は診断専用のためグラフ非表示)
      - X軸: Day (1〜7)
      - Y軸: 1〜5
      - スコア3の位置に赤破線（合格ライン）

    日本語フォント対応: matplotlib.rcParams で対応
    （IPAexGothic がなければフォールバック）

    生成後に plt.close() でリソースを解放する。
    """

## テスト
tests/test_visualization.py を作成:
- PipelineLog のサンプルデータからグラフ生成が正常完了すること
- 出力ファイルが存在すること
- plt.close() が呼ばれていること（リソースリーク防止）

## 完了条件
- python -m csdg.main --dry-run が正常終了する（終了コード 0）
- pytest tests/test_visualization.py -v が全件 Pass
- mypy, ruff がエラー 0

## MVP 動作確認
すべての Phase が完了したら、以下で実際のパイプラインを実行してください:

1. .env ファイルに CSDG_ANTHROPIC_API_KEY (または CSDG_GEMINI_API_KEY) を設定
2. python -m csdg.main --verbose を実行
3. output/ に day_01.md 〜 day_07.md, generation_log.json, state_trajectory.png が生成されることを確認
4. 生成された日記を読み、ペルソナの一貫性を目視確認
5. generation_log.json の CriticScore を確認
6. state_trajectory.png のグラフを確認
```

### 完了チェック
- [ ] `python -m csdg.main --dry-run` が動作する
- [ ] `save_diary` が YAMLフロントマター付きで出力する
- [ ] `generate_state_trajectory` がグラフを生成する
- [ ] テストが全件 Pass

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
---

## MVP 完了後の最終検証プロンプト

すべての Phase が完了したら、以下のプロンプトで最終検証を実行してください。

```
CSDG の MVP 実装が完了しました。以下の最終検証を実行してください。

## 1. 全テスト実行
pytest tests/ -v --cov=csdg --cov-report=term-missing -m "not e2e"

結果を報告してください:
- 全テスト数と Pass/Fail 数
- モジュール別カバレッジ
- カバレッジ目標との比較

## 2. 型チェック
mypy csdg/ --strict

エラーがあれば修正してください。

## 3. リンター
ruff check csdg/
ruff format csdg/ --check

エラーがあれば修正してください。

## 4. ドキュメントとの整合性確認
- csdg/ のモジュール構成が docs/repository-structure.md と一致しているか
- schemas.py のモデルが docs/architecture.md のスキーマ定義と一致しているか
- prompts/ のファイルが docs/repository-structure.md のプロンプト一覧と一致しているか

不一致があればドキュメントまたはコードを修正してください。

## 5. .steering/ の最終記録
.steering/[今日の日付]-mvp-final-verification/ を作成し、
最終検証の結果を記録してください。

## 6. （APIキーがある場合）E2E 実行
python -m csdg.main --verbose を実行し、以下を確認:
- 7日分の日記が output/ に生成されること
- generation_log.json の CriticScore を確認
- state_trajectory.png が生成されること
- 日記テキストのペルソナ一貫性（絵文字なし、断定なし、「わたし」一人称）

尚、実装する際は.claude内にあるサブエージェント、Skillなどを積極的に活用し、commandsなどに忠実に従って実装すること。 
結果を報告してください。
```

---

## Phase 間の依存関係サマリ

```
Phase 0: セットアップ
    ↓
Phase 1: schemas.py ─────────────────────────┐
    ↓                                         │
Phase 2: scenario.py ←── schemas.py           │
    ↓                                         │
Phase 3: config.py                            │
    ↓                                         │
Phase 4: prompts/ (コード非依存)              │
    ↓                                         │
Phase 5: llm_client.py ←── schemas.py ────────┤
    ↓                                         │
Phase 6: actor.py ←── llm_client, schemas, config, prompts
    ↓                                         │
Phase 7: critic.py ←── llm_client, schemas, config, prompts
    ↓                                         │
Phase 8: pipeline.py ←── actor, critic, schemas, config
    ↓
Phase 9: main.py ←── pipeline, config, scenario
         visualization.py ←── schemas
```
