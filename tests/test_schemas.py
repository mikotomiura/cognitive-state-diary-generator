"""csdg/schemas.py のバリデーションテスト。

全Pydanticモデルの正常系・異常系・境界値テストを網羅する。
test-standards/SKILL.md の AAA パターンおよび命名規約に従う。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from csdg.schemas import (
    CharacterState,
    CriticScore,
    DailyEvent,
    EmotionalDelta,
    GenerationRecord,
    LLMDeltaResponse,
    PipelineLog,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(**overrides: object) -> DailyEvent:
    """テスト用 DailyEvent を作成するヘルパー。"""
    defaults: dict[str, object] = {
        "day": 1,
        "event_type": "positive",
        "domain": "仕事",
        "description": "テスト用のイベント記述です",
        "emotional_impact": 0.5,
    }
    defaults.update(overrides)
    return DailyEvent(**defaults)  # type: ignore[arg-type]


def _make_state(**overrides: object) -> CharacterState:
    """テスト用 CharacterState を作成するヘルパー。"""
    defaults: dict[str, object] = {
        "fatigue": 0.0,
        "motivation": 0.0,
        "stress": 0.0,
        "current_focus": "テスト",
        "growth_theme": "テスト",
    }
    defaults.update(overrides)
    return CharacterState(**defaults)  # type: ignore[arg-type]


def _make_critic_score(**overrides: object) -> CriticScore:
    """テスト用 CriticScore を作成するヘルパー。"""
    defaults: dict[str, object] = {
        "temporal_consistency": 4,
        "emotional_plausibility": 4,
        "persona_deviation": 4,
    }
    defaults.update(overrides)
    return CriticScore(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# DailyEvent
# ===========================================================================


class TestDailyEventValidation:
    """DailyEvent のバリデーションテスト。"""

    def test_valid_event(self) -> None:
        """正常な値で DailyEvent が生成できる。"""
        event = _make_event()
        assert event.day == 1
        assert event.event_type == "positive"

    @pytest.mark.parametrize("event_type", ["positive", "negative", "neutral"])
    def test_valid_event_types(self, event_type: str) -> None:
        """許可された event_type が受け入れられる。"""
        event = _make_event(event_type=event_type)
        assert event.event_type == event_type

    @pytest.mark.parametrize("event_type", ["invalid", "POSITIVE", "ポジティブ", ""])
    def test_invalid_event_type(self, event_type: str) -> None:
        """不正な event_type で ValidationError が発生する。"""
        with pytest.raises(ValidationError, match="event_type"):
            _make_event(event_type=event_type)

    def test_empty_domain_rejected(self) -> None:
        """空文字列の domain で ValidationError が発生する。"""
        with pytest.raises(ValidationError, match="domain"):
            _make_event(domain="")

    def test_description_min_length(self) -> None:
        """10文字未満の description で ValidationError が発生する。"""
        with pytest.raises(ValidationError, match="description"):
            _make_event(description="短すぎる")

    def test_description_exactly_10_chars(self) -> None:
        """ちょうど10文字の description は受け入れられる。"""
        event = _make_event(description="1234567890")
        assert len(event.description) == 10

    @pytest.mark.parametrize(
        ("impact", "should_pass"),
        [
            (-1.0, True),
            (0.0, True),
            (1.0, True),
            (0.5, True),
            (-1.1, False),
            (1.1, False),
            (2.0, False),
            (-2.0, False),
        ],
    )
    def test_emotional_impact_range(self, impact: float, should_pass: bool) -> None:
        """emotional_impact の境界値テスト。"""
        if should_pass:
            event = _make_event(emotional_impact=impact)
            assert event.emotional_impact == impact
        else:
            with pytest.raises(ValidationError, match="emotional_impact"):
                _make_event(emotional_impact=impact)

    def test_frozen_model(self) -> None:
        """DailyEvent はイミュータブルである。"""
        event = _make_event()
        with pytest.raises(ValidationError):
            event.day = 2  # type: ignore[misc]


# ===========================================================================
# CharacterState
# ===========================================================================


class TestCharacterStateClamp:
    """CharacterState の連続変数クランプのテスト。"""

    @pytest.mark.parametrize(
        ("field", "raw", "expected"),
        [
            ("fatigue", 1.5, 1.0),
            ("fatigue", -1.5, 0.0),
            ("fatigue", 0.5, 0.5),
            ("fatigue", 1.0, 1.0),
            ("fatigue", -1.0, 0.0),
            ("fatigue", -0.5, 0.0),
            ("fatigue", 0.0, 0.0),
            ("motivation", 2.0, 1.0),
            ("motivation", -3.0, -1.0),
            ("motivation", 0.7, 0.7),
            ("stress", 1.1, 1.0),
            ("stress", -1.1, -1.0),
            ("stress", -0.5, -0.5),
        ],
    )
    def test_clamp_continuous(self, field: str, raw: float, expected: float) -> None:
        """連続変数はクランプされる (fatigue: 0.0〜1.0, motivation/stress: -1.0〜1.0)。"""
        state = _make_state(**{field: raw})
        assert getattr(state, field) == expected


class TestCharacterStateMemoryBuffer:
    """CharacterState の memory_buffer サイズ制限テスト。"""

    def test_buffer_within_limit(self) -> None:
        """3件以下の memory_buffer はそのまま保持される。"""
        state = _make_state(memory_buffer=["a", "b", "c"])
        assert state.memory_buffer == ["a", "b", "c"]

    def test_buffer_exceeds_limit(self) -> None:
        """4件以上の memory_buffer は末尾3件に制限される。"""
        state = _make_state(memory_buffer=["a", "b", "c", "d"])
        assert state.memory_buffer == ["b", "c", "d"]

    def test_buffer_five_items(self) -> None:
        """5件の memory_buffer は末尾3件に制限される。"""
        state = _make_state(memory_buffer=["a", "b", "c", "d", "e"])
        assert state.memory_buffer == ["c", "d", "e"]

    def test_empty_buffer(self) -> None:
        """空の memory_buffer はそのまま保持される。"""
        state = _make_state()
        assert state.memory_buffer == []

    def test_default_factory(self) -> None:
        """memory_buffer のデフォルトはインスタンス間で共有されない。"""
        state1 = _make_state()
        state2 = _make_state()
        assert state1.memory_buffer is not state2.memory_buffer


class TestCharacterStateDefaults:
    """CharacterState のデフォルト値テスト。"""

    def test_unresolved_issue_default(self) -> None:
        """unresolved_issue のデフォルトは None。"""
        state = _make_state()
        assert state.unresolved_issue is None

    def test_relationships_default(self) -> None:
        """relationships のデフォルトは空辞書。"""
        state = _make_state()
        assert state.relationships == {}


# ===========================================================================
# CriticScore
# ===========================================================================


class TestCriticScoreRange:
    """CriticScore のスコア範囲テスト。"""

    @pytest.mark.parametrize(
        "field",
        ["temporal_consistency", "emotional_plausibility", "persona_deviation"],
    )
    @pytest.mark.parametrize("value", [3, 4, 5])
    def test_valid_score_pass(self, field: str, value: int) -> None:
        """3〜5のスコア (Pass) は reject_reason なしで受け入れられる。"""
        score = _make_critic_score(**{field: value})
        assert getattr(score, field) == value

    @pytest.mark.parametrize(
        "field",
        ["temporal_consistency", "emotional_plausibility", "persona_deviation"],
    )
    @pytest.mark.parametrize("value", [1, 2])
    def test_valid_score_reject(self, field: str, value: int) -> None:
        """1〜2のスコア (Reject) は reject_reason 付きで受け入れられる。"""
        score = _make_critic_score(
            **{field: value},
            reject_reason="テスト理由",
            revision_instruction="テスト指示",
        )
        assert getattr(score, field) == value

    @pytest.mark.parametrize(
        "field",
        ["temporal_consistency", "emotional_plausibility", "persona_deviation"],
    )
    @pytest.mark.parametrize("value", [0, -1, 6, 10])
    def test_invalid_score(self, field: str, value: int) -> None:
        """範囲外のスコアで ValidationError が発生する。"""
        with pytest.raises(ValidationError, match="スコアは1〜5の範囲"):
            _make_critic_score(**{field: value})


class TestCriticScoreRejectValidation:
    """CriticScore の Reject 時必須フィールドテスト。"""

    def test_pass_without_reason(self) -> None:
        """全スコア3以上 (Pass) では reject_reason は不要。"""
        score = _make_critic_score(
            temporal_consistency=3,
            emotional_plausibility=3,
            persona_deviation=3,
        )
        assert score.reject_reason is None

    def test_reject_with_both_fields(self) -> None:
        """Reject時に reject_reason と revision_instruction があれば有効。"""
        score = _make_critic_score(
            temporal_consistency=2,
            reject_reason="整合性が不足",
            revision_instruction="過去の日記との矛盾を解消してください",
        )
        assert score.reject_reason is not None
        assert score.revision_instruction is not None

    def test_reject_without_reason_raises(self) -> None:
        """Reject時に reject_reason がないと ValidationError。"""
        with pytest.raises(ValidationError, match="reject_reason"):
            _make_critic_score(
                temporal_consistency=2,
                revision_instruction="修正してください",
            )

    def test_reject_without_instruction_raises(self) -> None:
        """Reject時に revision_instruction がないと ValidationError。"""
        with pytest.raises(ValidationError, match="revision_instruction"):
            _make_critic_score(
                temporal_consistency=2,
                reject_reason="理由あり",
            )


# ===========================================================================
# JSON 往復変換 (Roundtrip Serialization)
# ===========================================================================


class TestRoundtripSerialization:
    """JSON 往復変換テスト。"""

    def test_daily_event_roundtrip(self) -> None:
        """DailyEvent の JSON 往復変換で値が保持される。"""
        original = _make_event()
        restored = DailyEvent.model_validate_json(original.model_dump_json())
        assert original == restored

    def test_character_state_roundtrip(self) -> None:
        """CharacterState の JSON 往復変換で値が保持される。"""
        original = _make_state(
            fatigue=0.5,
            motivation=-0.3,
            stress=0.1,
            memory_buffer=["day1", "day2"],
            relationships={"深森那由他": 0.8},
        )
        restored = CharacterState.model_validate_json(original.model_dump_json())
        assert original == restored

    def test_critic_score_roundtrip(self) -> None:
        """CriticScore の JSON 往復変換で値が保持される。"""
        original = _make_critic_score()
        restored = CriticScore.model_validate_json(original.model_dump_json())
        assert original == restored

    def test_generation_record_roundtrip(self) -> None:
        """GenerationRecord の JSON 往復変換で値が保持される。"""
        original = GenerationRecord(
            day=1,
            event=_make_event(),
            initial_state=_make_state(),
            final_state=_make_state(fatigue=0.3),
            diary_text="今日の日記",
            critic_scores=[_make_critic_score()],
            retry_count=0,
            fallback_used=False,
            temperature_used=0.7,
            phase1_duration_ms=100,
            phase2_duration_ms=200,
            phase3_duration_ms=150,
            expected_delta={"stress": -0.15},
            actual_delta={"stress": -0.1},
            deviation={"stress": 0.05},
        )
        restored = GenerationRecord.model_validate_json(original.model_dump_json())
        assert original == restored

    def test_pipeline_log_roundtrip(self) -> None:
        """PipelineLog の JSON 往復変換で値が保持される。"""
        record = GenerationRecord(
            day=1,
            event=_make_event(),
            initial_state=_make_state(),
            final_state=_make_state(fatigue=0.3),
            diary_text="今日の日記",
            critic_scores=[_make_critic_score()],
            retry_count=0,
            fallback_used=False,
            temperature_used=0.7,
            phase1_duration_ms=100,
            phase2_duration_ms=200,
            phase3_duration_ms=150,
            expected_delta={"stress": -0.15},
            actual_delta={"stress": -0.1},
            deviation={"stress": 0.05},
        )
        original = PipelineLog(
            executed_at=datetime(2026, 3, 25, tzinfo=UTC),
            config_summary={"model": "gpt-4o", "temperature": 0.7},
            prompt_hashes={"System_Persona": "abc123"},
            records=[record],
            total_duration_ms=1000,
            total_api_calls=3,
            total_retries=0,
            total_fallbacks=0,
        )
        restored = PipelineLog.model_validate_json(original.model_dump_json())
        assert original == restored


# ---------------------------------------------------------------------------
# LLMDeltaResponse のテスト
# ---------------------------------------------------------------------------


class TestLLMDeltaResponse:
    """LLMDeltaResponse のバリデーションテスト."""

    def test_valid_response(self) -> None:
        """正常な LLMDeltaResponse を作成できる."""
        resp = LLMDeltaResponse(
            delta=EmotionalDelta(fatigue=0.1, motivation=-0.2, stress=0.3),
            reason="上司に叱責されたためストレス上昇",
        )
        assert resp.reason == "上司に叱責されたためストレス上昇"
        assert resp.delta.stress == pytest.approx(0.3)

    def test_empty_reason_raises(self) -> None:
        """reason が空文字列の場合に ValidationError."""
        with pytest.raises(ValidationError, match="reason は空文字列不可"):
            LLMDeltaResponse(
                delta=EmotionalDelta(),
                reason="",
            )

    def test_whitespace_only_reason_raises(self) -> None:
        """reason がスペースのみの場合に ValidationError."""
        with pytest.raises(ValidationError, match="reason は空文字列不可"):
            LLMDeltaResponse(
                delta=EmotionalDelta(),
                reason="   ",
            )

    def test_roundtrip_serialization(self) -> None:
        """JSON シリアライズ/デシリアライズの往復テスト."""
        original = LLMDeltaResponse(
            delta=EmotionalDelta(fatigue=0.1, motivation=-0.2, stress=0.3),
            reason="テスト理由",
        )
        restored = LLMDeltaResponse.model_validate_json(original.model_dump_json())
        assert original == restored


# ====================================================================
# ShortTermMemory のウィンドウサイズ制限
# ====================================================================


class TestShortTermMemoryWindowSize:
    """ShortTermMemory が window_size でエントリを制限することのテスト。"""

    def test_entries_trimmed_to_window_size(self) -> None:
        """entries が window_size を超えた場合、末尾 window_size 件に制限される。"""
        from csdg.schemas import ShortTermMemory

        stm = ShortTermMemory(window_size=3, entries=[f"e{i}" for i in range(8)])
        assert len(stm.entries) == 3
        assert stm.entries[0] == "e5"
        assert stm.entries[-1] == "e7"

    def test_entries_within_window_size_not_trimmed(self) -> None:
        """entries が window_size 以下の場合は変更されない。"""
        from csdg.schemas import ShortTermMemory

        stm = ShortTermMemory(window_size=5, entries=["a", "b", "c"])
        assert len(stm.entries) == 3
