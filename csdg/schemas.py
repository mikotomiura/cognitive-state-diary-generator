"""CSDG Pydantic データモデル定義。

体系的認知モデルに基づくAIキャラクター日記生成システムで使用する
全データモデルを定義する。各モデルは architecture.md §2, §3 および
glossary.md §2 の仕様に準拠する。
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import BaseModel, Field, field_validator, model_validator


class DailyEvent(BaseModel):
    """日次イベント (x_t)。

    1日に起きる出来事を構造化したデータモデル。
    シナリオ設計時に事前定義され、パイプラインの入力として使用される。
    イミュータブルであり、生成後の変更は不可。
    """

    model_config = {"frozen": True}

    day: int = Field(description="経過日数 (1〜7)")
    event_type: str = Field(description="イベントの種類 (positive / negative / neutral)")
    domain: str = Field(description="イベントの領域 (仕事 / 人間関係 / 趣味 / 内省 / 思想)")
    description: str = Field(description="出来事の客観的な記述 (10文字以上)")
    emotional_impact: float = Field(description="感情的インパクト (-1.0〜+1.0)")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """許可された値のみを受け入れる。"""
        allowed = {"positive", "negative", "neutral"}
        if v not in allowed:
            raise ValueError(f"event_type は {allowed} のいずれか: {v}")
        return v

    @field_validator("domain")
    @classmethod
    def validate_domain_not_empty(cls, v: str) -> str:
        """空文字列を拒否する。"""
        if not v:
            raise ValueError("domain は空文字列不可")
        return v

    @field_validator("description")
    @classmethod
    def validate_min_length(cls, v: str) -> str:
        """10文字未満の文字列を拒否する。"""
        if len(v) < 10:
            raise ValueError(f"description は10文字以上必要: {len(v)}文字")
        return v

    @field_validator("emotional_impact")
    @classmethod
    def validate_emotional_impact_range(cls, v: float) -> float:
        """感情的インパクトが -1.0〜1.0 の範囲外の場合はエラー。"""
        if not (-1.0 <= v <= 1.0):
            raise ValueError(f"emotional_impact は -1.0〜1.0 の範囲: {v}")
        return v


class CharacterState(BaseModel):
    """キャラクター内部状態 (h_t)。

    ある時点でのキャラクターの感情・記憶・関心事を構造化したデータモデル。
    連続変数は -1.0〜1.0 にクランプされ、memory_buffer は最大3件に自動制限される。
    """

    fatigue: float = Field(description="疲労度 (-1.0: 絶好調 〜 1.0: 限界)")
    motivation: float = Field(description="モチベーション (-1.0: 虚無 〜 1.0: やる気満々)")
    stress: float = Field(description="ストレス値 (-1.0: リラックス 〜 1.0: 爆発寸前)")
    current_focus: str = Field(description="現在最も関心を持っている事柄")
    unresolved_issue: str | None = Field(default=None, description="未解決の悩みや課題")
    growth_theme: str = Field(description="1週間を通じた成長テーマ")
    memory_buffer: list[str] = Field(default_factory=list, description="過去3日分のdaily_summary")
    relationships: dict[str, float] = Field(default_factory=dict, description="人物への好感度")

    @field_validator("fatigue", "motivation", "stress")
    @classmethod
    def clamp_continuous(cls, v: float) -> float:
        """連続変数を -1.0〜1.0 にクランプする。"""
        return max(-1.0, min(1.0, v))

    @field_validator("memory_buffer")
    @classmethod
    def limit_buffer(cls, v: list[str]) -> list[str]:
        """memory_buffer を最大3件に制限する(FIFO)。"""
        return v[-3:] if len(v) > 3 else v


class EmotionalDelta(BaseModel):
    """感情パラメータの変化量 (delta)。

    LLMが提案する補正値、または数式で算出された変動幅を表現する。
    各値は clamp 前の生の delta 値であり、最終的な状態適用時にクランプされる。
    """

    fatigue: float = Field(default=0.0, description="疲労度の変化量")
    motivation: float = Field(default=0.0, description="モチベーションの変化量")
    stress: float = Field(default=0.0, description="ストレス値の変化量")


class LLMDeltaResponse(BaseModel):
    """LLM が返す delta 補正値と理由。

    LLM に delta を返させる際、変化の理由を併記させることで
    デバッグ時に「なぜこの状態遷移が起きたか」を追跡可能にする。
    """

    delta: EmotionalDelta = Field(description="各軸の補正値")
    reason: str = Field(description="deltaの変化理由 (例: 上司に叱責されたためストレス上昇)")

    @field_validator("reason")
    @classmethod
    def validate_reason_not_empty(cls, v: str) -> str:
        """reason が空文字列の場合はエラー。"""
        if not v.strip():
            raise ValueError("reason は空文字列不可")
        return v


class CriticScore(BaseModel):
    """評価器スコア。

    Criticが出力する評価結果。3つのスコア(各1〜5)で構成され、
    全スコアが3以上で Pass、1つでも3未満があれば Reject となる。
    Reject時は reject_reason と revision_instruction が必須。
    """

    temporal_consistency: int = Field(description="時間的整合性スコア (1〜5)")
    emotional_plausibility: int = Field(description="感情的妥当性スコア (1〜5)")
    persona_deviation: int = Field(description="ペルソナ維持度スコア (1〜5)")
    reject_reason: str | None = Field(default=None, description="リジェクト時の理由")
    revision_instruction: str | None = Field(default=None, description="修正指示")

    @field_validator("temporal_consistency", "emotional_plausibility", "persona_deviation")
    @classmethod
    def validate_score_range(cls, v: int) -> int:
        """スコアが1〜5の範囲外の場合は ValidationError を発生させる。"""
        if not (1 <= v <= 5):
            raise ValueError(f"スコアは1〜5の範囲: {v}")
        return v

    @model_validator(mode="after")
    def check_reject_fields(self) -> CriticScore:
        """Reject時はreject_reasonとrevision_instructionが必須。"""
        is_reject = any(
            getattr(self, f) < 3 for f in ["temporal_consistency", "emotional_plausibility", "persona_deviation"]
        )
        if is_reject and not self.reject_reason:
            raise ValueError("Reject時はreject_reasonが必須")
        if is_reject and not self.revision_instruction:
            raise ValueError("Reject時はrevision_instructionが必須")
        return self


class TurningPoint(BaseModel):
    """物語の転換点。

    長期記憶に蓄積される、キャラクターの内面的変化が起きた重要な日の記録。
    """

    day: int = Field(description="転換点が発生した経過日数")
    summary: str = Field(description="転換点の要約 (1-2文)")


class LongTermMemory(BaseModel):
    """長期記憶: 抽象化された信念・テーマ・転換点。

    スライディングウィンドウから押し出されたエントリから
    重要な情報を抽出・蓄積する。
    """

    beliefs: list[str] = Field(default_factory=list, description="蓄積された信念")
    recurring_themes: list[str] = Field(default_factory=list, description="繰り返し現れるテーマ")
    turning_points: list[TurningPoint] = Field(default_factory=list, description="転換点のリスト")


class ShortTermMemory(BaseModel):
    """短期記憶: 直近N日の生テキスト (現行 memory_buffer と同等)。"""

    window_size: int = Field(default=3, description="ウィンドウサイズ")
    entries: list[str] = Field(default_factory=list, description="直近N日分の日記要約")

    @field_validator("entries")
    @classmethod
    def limit_entries(cls, v: list[str]) -> list[str]:
        """entries を window_size の最大値 (10) に制限する安全弁。"""
        return v[-10:] if len(v) > 10 else v


class Memory(BaseModel):
    """2層メモリ構造: 短期記憶 + 長期記憶。"""

    short_term: ShortTermMemory = Field(default_factory=ShortTermMemory)
    long_term: LongTermMemory = Field(default_factory=LongTermMemory)


class MemoryExtraction(BaseModel):
    """LLM が抽出した長期記憶の信念・テーマ。"""

    new_beliefs: list[str] = Field(default_factory=list, description="追加すべき信念")
    new_themes: list[str] = Field(default_factory=list, description="追加すべきテーマ")


class LayerScore(BaseModel):
    """各層の個別スコア (デバッグ用)。

    CriticPipeline の各層 (RuleBased / Statistical / LLMJudge) が
    出力するスコアとメタデータを保持する。
    """

    temporal_consistency: float = Field(description="時間的整合性スコア (1.0〜5.0)")
    emotional_plausibility: float = Field(description="感情的妥当性スコア (1.0〜5.0)")
    persona_deviation: float = Field(description="ペルソナ維持度スコア (1.0〜5.0)")
    details: dict[str, object] = Field(default_factory=dict, description="層固有のメタデータ")


class CriticResult(BaseModel):
    """CriticPipeline の3層統合結果。

    各層のスコアとメタデータ、および最終統合スコア (CriticScore) を保持する。
    既存の CriticScore との後方互換性を維持する。
    """

    rule_based: LayerScore = Field(description="Layer 1: RuleBasedValidator のスコア")
    statistical: LayerScore = Field(description="Layer 2: StatisticalChecker のスコア")
    llm_judge: LayerScore = Field(description="Layer 3: LLMJudge のスコア")
    final_score: CriticScore = Field(description="3層統合後の最終 CriticScore")
    weights: dict[str, float] = Field(
        default_factory=lambda: {"rule_based": 0.3, "statistical": 0.2, "llm_judge": 0.5},
        description="各層の重み",
    )
    inverse_estimation_score: float | None = Field(
        default=None,
        description="逆推定一致スコア (1-5): テキストから推定される感情状態と入力値の一致度",
    )
    veto_applied: dict[str, bool] = Field(
        default_factory=dict,
        description="各軸で veto が発動されたかのフラグ",
    )


class GenerationRecord(BaseModel):
    """1Dayの生成記録。

    パイプラインが1日分の日記を生成した際の全情報を記録する。
    デバッグ、品質分析、リトライ頻度の追跡に使用される。
    """

    day: int = Field(description="経過日数 (1〜7)")
    event: DailyEvent = Field(description="入力イベント")
    initial_state: CharacterState = Field(description="Phase 1 入力時の状態 (h_{t-1})")
    final_state: CharacterState = Field(description="Phase 1 出力時の状態 (h_t)")
    diary_text: str = Field(description="Phase 2 で生成された日記本文")
    critic_scores: list[CriticScore] = Field(description="Phase 3 の評価結果リスト (リトライ分含む)")
    retry_count: int = Field(description="リトライ回数")
    fallback_used: bool = Field(description="フォールバックが使用されたか")
    temperature_used: float = Field(description="最終的に使用された temperature")
    phase1_duration_ms: int = Field(description="Phase 1 の処理時間 (ミリ秒)")
    phase2_duration_ms: int = Field(description="Phase 2 の処理時間 (ミリ秒)")
    phase3_duration_ms: int = Field(description="Phase 3 の処理時間 (ミリ秒)")
    expected_delta: dict[str, float] = Field(description="期待変動幅")
    actual_delta: dict[str, float] = Field(description="実際の変動幅")
    deviation: dict[str, float] = Field(description="期待値との乖離")


class PipelineLog(BaseModel):
    """パイプライン全体ログ。

    7日間のパイプライン実行全体の記録。
    実行設定、プロンプトのハッシュ、各日の生成記録、集計値を含む。
    """

    pipeline_version: str = Field(default="1.0.0", description="パイプラインバージョン")
    executed_at: datetime = Field(description="実行開始日時")
    config_summary: dict[str, object] = Field(description="実行時の設定サマリー")
    prompt_hashes: dict[str, str] = Field(description="使用したプロンプトファイルのハッシュ")
    records: list[GenerationRecord] = Field(description="各日の生成記録")
    total_duration_ms: int = Field(description="パイプライン全体の処理時間 (ミリ秒)")
    total_api_calls: int = Field(description="API呼び出し総数")
    total_retries: int = Field(description="リトライ総数")
    total_fallbacks: int = Field(description="フォールバック総数")
