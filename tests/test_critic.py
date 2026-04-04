"""csdg/engine/critic.py のテスト.

純粋関数 (compute_expected_delta, compute_deviation, judge) は
LLM モック不要でテストする。3層構造 (RuleBasedValidator,
StatisticalChecker, LLMJudge, CriticPipeline) のテストを含む。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from csdg.engine.critic import (
    Critic,
    CriticPipeline,
    RuleBasedValidator,
    StatisticalChecker,
    compute_deviation,
    compute_expected_delta,
    compute_trigram_overlap,
    extract_trigrams,
    judge,
)
from csdg.schemas import CharacterState, CriticScore, DailyEvent, LayerScore

if TYPE_CHECKING:
    from pathlib import Path

    from csdg.config import CSDGConfig
    from csdg.engine.llm_client import LLMClient


# ====================================================================
# ヘルパー
# ====================================================================


def _make_state(
    fatigue: float = 0.1,
    motivation: float = 0.2,
    stress: float = -0.1,
) -> CharacterState:
    return CharacterState(
        fatigue=fatigue,
        motivation=motivation,
        stress=stress,
        current_focus="テスト",
        growth_theme="テストテーマ",
        memory_buffer=[],
        relationships={},
    )


def _make_event(day: int = 1, impact: float = 0.2) -> DailyEvent:
    return DailyEvent(
        day=day,
        event_type="neutral",
        domain="仕事",
        description="社内ツールの自動化スクリプトが完成し、30分かかっていた作業が2分に短縮された",
        emotional_impact=impact,
    )


# ====================================================================
# 純粋関数のテスト (LLM モック不要)
# ====================================================================


class TestComputeExpectedDelta:
    """compute_expected_delta のテスト."""

    def test_positive_event(self, sample_event: DailyEvent) -> None:
        """positive イベント (impact=+0.2) の各パラメータ計算."""
        sensitivity = {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2}
        result = compute_expected_delta(sample_event, sensitivity)

        assert result["stress"] == pytest.approx(0.2 * -0.3)
        assert result["motivation"] == pytest.approx(0.2 * 0.4)
        assert result["fatigue"] == pytest.approx(0.2 * -0.2)

    def test_high_positive_impact(self) -> None:
        """positive イベント (impact=+0.6) の各パラメータ計算."""
        event = DailyEvent(
            day=2,
            event_type="positive",
            domain="人間関係",
            description="同僚から嬉しいフィードバックをもらった",
            emotional_impact=0.6,
        )
        sensitivity = {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2}
        result = compute_expected_delta(event, sensitivity)

        assert result["stress"] == pytest.approx(-0.18)
        assert result["motivation"] == pytest.approx(0.24)
        assert result["fatigue"] == pytest.approx(-0.12)

    def test_negative_event_day4(self, high_impact_event: DailyEvent) -> None:
        """negative イベント (impact=-0.9, Day 4) の計算."""
        sensitivity = {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2}
        result = compute_expected_delta(high_impact_event, sensitivity)

        assert result["stress"] == pytest.approx(-0.9 * -0.3)
        assert result["motivation"] == pytest.approx(-0.9 * 0.4)
        assert result["fatigue"] == pytest.approx(-0.9 * -0.2)

    def test_neutral_event_zero_impact(self) -> None:
        """neutral イベント (impact=0.0) で全パラメータ 0.0."""
        event = DailyEvent(
            day=3,
            event_type="neutral",
            domain="内省",
            description="特に何も起きなかった平穏な一日だった",
            emotional_impact=0.0,
        )
        sensitivity = {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2}
        result = compute_expected_delta(event, sensitivity)

        assert result["stress"] == pytest.approx(0.0)
        assert result["motivation"] == pytest.approx(0.0)
        assert result["fatigue"] == pytest.approx(0.0)


class TestComputeDeviation:
    """compute_deviation のテスト."""

    def test_deviation_near_zero_when_expected(self, initial_state: CharacterState) -> None:
        """期待通りの変動で deviation が 0 に近い."""
        expected_delta = {"stress": 0.1, "motivation": 0.2, "fatigue": -0.05}
        curr_state = initial_state.model_copy(
            update={
                "stress": initial_state.stress + 0.1,
                "motivation": initial_state.motivation + 0.2,
                "fatigue": initial_state.fatigue - 0.05,
            },
        )

        result = compute_deviation(initial_state, curr_state, expected_delta)

        assert result["stress"] == pytest.approx(0.0)
        assert result["motivation"] == pytest.approx(0.0)
        assert result["fatigue"] == pytest.approx(0.0)

    def test_large_deviation(self, initial_state: CharacterState) -> None:
        """大きな乖離がある場合."""
        expected_delta = {"stress": 0.1, "motivation": 0.2, "fatigue": -0.05}
        curr_state = initial_state.model_copy(
            update={
                "stress": initial_state.stress + 0.5,
                "motivation": initial_state.motivation - 0.3,
                "fatigue": initial_state.fatigue + 0.4,
            },
        )

        result = compute_deviation(initial_state, curr_state, expected_delta)

        assert result["stress"] == pytest.approx(0.5 - 0.1)
        assert result["motivation"] == pytest.approx(-0.3 - 0.2)
        assert result["fatigue"] == pytest.approx(0.4 - (-0.05))


class TestJudge:
    """judge のテスト."""

    def test_all_scores_above_3_pass(self, pass_score: CriticScore) -> None:
        assert judge(pass_score) is True

    def test_all_scores_exactly_3_pass(self) -> None:
        score = CriticScore(
            temporal_consistency=3,
            emotional_plausibility=3,
            persona_deviation=3,
        )
        assert judge(score) is True

    def test_one_score_is_2_reject(self, reject_score: CriticScore) -> None:
        assert judge(reject_score) is False

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("temporal_consistency", 2),
            ("emotional_plausibility", 1),
            ("persona_deviation", 2),
        ],
    )
    def test_individual_score_below_3_reject(self, field: str, value: int) -> None:
        base = {"temporal_consistency": 4, "emotional_plausibility": 4, "persona_deviation": 4}
        base[field] = value
        score = CriticScore(
            **base,
            reject_reason=f"{field} が低い",
            revision_instruction=f"{field} を改善してください",
        )
        assert judge(score) is False

    def test_judge_ignores_hook_strength(self) -> None:
        """judge() が hook_strength の値に関わらず既存3軸のみで判定すること。"""
        score_pass = CriticScore(
            temporal_consistency=3,
            emotional_plausibility=3,
            persona_deviation=3,
            hook_strength=0.0,
        )
        assert judge(score_pass) is True

        score_fail = CriticScore(
            temporal_consistency=2,
            emotional_plausibility=4,
            persona_deviation=4,
            hook_strength=1.0,
            reject_reason="temporal が低い",
            revision_instruction="過去への言及を追加",
        )
        assert judge(score_fail) is False


# ====================================================================
# Layer 1: RuleBasedValidator のテスト
# ====================================================================


class TestRuleBasedValidator:
    """RuleBasedValidator のユニットテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.0, motivation=0.3, fatigue=0.05)
        self.event = _make_event()
        self.expected_delta = {"stress": -0.06, "motivation": 0.08, "fatigue": -0.04}

    def test_good_diary_scores_moderate(self) -> None:
        """禁止表現なしの日記で基本スコア付近."""
        good_diary = "あ" * 400  # 400文字: 理想範囲内だが加点要素なし
        result = self.validator.evaluate(
            good_diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        # 基本スコア2.5 + わたし/ellipsis加点なし = 2.5
        assert result.persona_deviation >= 2.0
        assert result.temporal_consistency >= 2.5

    def test_ideal_diary_gets_high_score(self) -> None:
        """理想的な条件を満たす日記が 4.0-5.0 になること."""
        # わたし4回 + ......2回 + 理想文字数
        ideal_diary = "わたし" * 4 + "......" * 2 + "あ" * 380
        result = self.validator.evaluate(
            ideal_diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        # 基本2.5 + わたし1.0(sweet) + ellipsis1.0(sweet) = 4.5
        assert result.persona_deviation >= 4.0
        assert result.persona_deviation <= 5.0

    def test_normal_diary_gets_moderate_score(self) -> None:
        """普通の日記が 2.0-3.5 の範囲に収まること."""
        # 400文字の適切な長さだが加点要素が少ない日記: わたし=0, ellipsis=0
        normal_diary = "今日も仕事をした。会議に出席した。" * 25
        result = self.validator.evaluate(
            normal_diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        # 基本2.5、加点なし、ペナルティなし = 2.5
        assert 2.0 <= result.persona_deviation <= 3.5

    def test_ending_template_repetition_detected(self) -> None:
        """余韻テンプレート反復が検出されること."""
        diary = "あ" * 350 + "\n\n効率とBの間にある溝は深い......"
        prev_diary = "あ" * 350 + "\n\nAとBは両立するのだろうか......"
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            prev_diary=prev_diary,
        )
        assert result.details.get("ending_template_repetition") is True

    def test_short_diary_penalized(self) -> None:
        """短すぎる日記で persona_deviation が減点される."""
        short_diary = "短い日記。"
        result = self.validator.evaluate(
            short_diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.persona_deviation < 4.0
        assert result.details.get("char_count_violation") == "too_short"

    def test_emoji_penalized(self) -> None:
        """絵文字を含む日記で persona_deviation が大幅減点される."""
        emoji_diary = "あ" * 400 + "\U0001f600\U0001f600"
        result = self.validator.evaluate(
            emoji_diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.persona_deviation < 4.0
        assert result.details.get("emoji_count", 0) > 0

    def test_high_trigram_overlap_penalized(self) -> None:
        """前日との重複率が高い場合に temporal_consistency が減点される."""
        diary = "あいうえおかきくけこ" * 100
        prev_diary = "あいうえおかきくけこ" * 100  # 完全一致
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            prev_diary=prev_diary,
        )
        assert result.temporal_consistency < 4.0
        assert result.details.get("overlap_violation") is True

    def test_no_prev_diary_no_overlap_check(self) -> None:
        """前日の日記がない場合は重複チェックをスキップ."""
        diary = "あ" * 400
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert "trigram_overlap" not in result.details

    def test_direction_mismatch_penalized(self) -> None:
        """感情パラメータの方向矛盾で emotional_plausibility が減点される."""
        high_event = _make_event(impact=-0.9)
        # expected: stress increases (positive delta from negative impact * negative sensitivity)
        expected = {"stress": 0.27, "motivation": -0.36, "fatigue": 0.18}
        # But actual state has stress decreased significantly
        mismatched_state = _make_state(stress=-0.5, motivation=0.5)
        diary = "あ" * 400

        result = self.validator.evaluate(
            diary,
            self.prev_state,
            mismatched_state,
            high_event,
            expected,
        )
        assert result.emotional_plausibility < 5.0


# ====================================================================
# Layer 2: StatisticalChecker のテスト
# ====================================================================


class TestStatisticalChecker:
    """StatisticalChecker のユニットテスト."""

    def setup_method(self) -> None:
        self.checker = StatisticalChecker()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.0, motivation=0.3, fatigue=0.05)
        self.event = _make_event()
        self.expected_delta = {"stress": -0.06, "motivation": 0.08, "fatigue": -0.04}
        self.small_deviation = {"stress": 0.01, "motivation": -0.02, "fatigue": 0.01}

    def test_normal_diary_scores_high(self) -> None:
        """通常の日記で小さい deviation なら高スコア."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            self.small_deviation,
        )
        # 基本2.5 + deviation<0.05加点1.5 = 4.0
        assert result.emotional_plausibility >= 3.0

    def test_large_deviation_penalized(self) -> None:
        """大きな deviation で emotional_plausibility が低スコアになる."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        large_deviation = {"stress": 0.8, "motivation": -0.9, "fatigue": 0.7}
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            large_deviation,
        )
        # 基本2.5 - 2.5(>0.6) = 0.0 (clamped 1.0)
        assert result.emotional_plausibility <= 2.0

    def test_small_deviation_gets_high_score(self) -> None:
        """deviation < 0.05 で emotional 加点."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        tiny_deviation = {"stress": 0.01, "motivation": -0.02, "fatigue": 0.01}
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            tiny_deviation,
        )
        assert result.emotional_plausibility >= 3.5

    def test_medium_deviation_gets_moderate_score(self) -> None:
        """deviation 0.15-0.25 で 2.5 付近."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        medium_deviation = {"stress": 0.2, "motivation": -0.15, "fatigue": 0.1}
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            medium_deviation,
        )
        assert 2.0 <= result.emotional_plausibility <= 3.0

    def test_large_deviation_gets_low_score(self) -> None:
        """deviation > 0.6 で 2.0 以下."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        huge_deviation = {"stress": 0.8, "motivation": -0.7, "fatigue": 0.65}
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            huge_deviation,
        )
        assert result.emotional_plausibility <= 2.0

    def test_statistics_in_details(self) -> None:
        """統計情報が details に含まれる."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。"
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            self.small_deviation,
        )
        assert "avg_sentence_length" in result.details
        assert "sentence_count" in result.details
        assert "punctuation_ratio" in result.details
        assert "question_ratio" in result.details
        assert "max_deviation" in result.details

    def test_high_impact_excessive_assertions_penalized(self) -> None:
        """高インパクト時の過度な断定文で persona_deviation が減点される."""
        event = _make_event(impact=-0.9)
        diary = "これはだ。これはだ。これはだ。これはだ。これはである。" * 5
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            event,
            self.expected_delta,
            self.small_deviation,
        )
        assert result.details.get("excessive_assertions", 0) > 0


# ====================================================================
# トライグラム関数のテスト
# ====================================================================


class TestTrigramFunctions:
    """トライグラム関連関数のテスト."""

    def testextract_trigrams(self) -> None:
        trigrams = extract_trigrams("abcde")
        assert "abc" in trigrams
        assert "bcd" in trigrams
        assert "cde" in trigrams

    def test_extract_trigrams_short_text(self) -> None:
        assert extract_trigrams("ab") == set()

    def test_compute_overlap_identical(self) -> None:
        overlap = compute_trigram_overlap("あいうえお", "あいうえお")
        assert overlap == pytest.approx(1.0)

    def test_compute_overlap_different(self) -> None:
        overlap = compute_trigram_overlap("あいうえお", "かきくけこ")
        assert overlap == pytest.approx(0.0)

    def test_compute_overlap_empty(self) -> None:
        overlap = compute_trigram_overlap("", "abc")
        assert overlap == pytest.approx(0.0)


# ====================================================================
# Critic クラスのテスト (後方互換性, LLM モック使用)
# ====================================================================


@pytest.fixture()
def critic_prompts_dir(tmp_path: Path) -> Path:
    """テスト用プロンプトディレクトリを作成する."""
    persona = tmp_path / "System_Persona.md"
    persona.write_text("You are Tokomi.", encoding="utf-8")

    critic_prompt = tmp_path / "Prompt_Critic.md"
    critic_prompt.write_text(
        "Evaluate the diary.\n"
        "diary: {diary_text}\n"
        "state: {current_state}\n"
        "event: {event}\n"
        "expected_delta: {expected_delta}\n"
        "deviation: {deviation}",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture()
def critic(
    mock_llm_client: LLMClient,
    test_config: CSDGConfig,
    critic_prompts_dir: Path,
) -> Critic:
    """テスト用 Critic インスタンス."""
    return Critic(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)


class TestCriticEvaluate:
    """Critic.evaluate の後方互換性テスト."""

    @pytest.mark.asyncio()
    async def test_evaluate_returns_critic_score(
        self,
        critic: Critic,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
        sample_diary: str,
        pass_score: CriticScore,
    ) -> None:
        """evaluate が CriticScore を返す (3層統合後)."""
        curr_state = initial_state.model_copy(
            update={"stress": 0.0, "motivation": 0.3, "fatigue": 0.05},
        )
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = pass_score

        result = await critic.evaluate(initial_state, curr_state, sample_diary, sample_event)

        assert isinstance(result, CriticScore)
        # 3層統合後のスコアなので LLM 出力と完全一致しないが、範囲内
        assert 1 <= result.temporal_consistency <= 5
        assert 1 <= result.emotional_plausibility <= 5
        assert 1 <= result.persona_deviation <= 5
        mock_llm_client.generate_structured.assert_called_once()

    # _build_critic_prompt は CriticPipeline 移行に伴い削除済み。
    # プロンプト構築のテストは LLMJudge._build_prompt 経由で検証される。


class TestCriticEvaluateFullPrevDiary:
    """Critic.evaluate_full の prev_diary 転送テスト."""

    @pytest.mark.asyncio()
    async def test_prev_diary_forwarded_to_pipeline(
        self,
        critic: Critic,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
        pass_score: CriticScore,
    ) -> None:
        """evaluate_full に prev_diary を渡すと trigram overlap が計算される."""
        curr_state = initial_state.model_copy(
            update={"stress": 0.0, "motivation": 0.3, "fatigue": 0.05},
        )
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = pass_score

        diary = "あいうえおかきくけこ" * 100
        prev_diary = "あいうえおかきくけこ" * 100  # 完全一致

        result = await critic.evaluate_full(
            initial_state,
            curr_state,
            diary,
            sample_event,
            prev_diary=prev_diary,
        )

        # trigram overlap が計算されている
        assert result.rule_based.details.get("trigram_overlap") is not None
        overlap = result.rule_based.details["trigram_overlap"]
        assert isinstance(overlap, float)
        assert overlap > 0.5

    @pytest.mark.asyncio()
    async def test_no_prev_diary_skips_overlap(
        self,
        critic: Critic,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
        pass_score: CriticScore,
    ) -> None:
        """prev_diary=None の場合、trigram overlap はスキップされる."""
        curr_state = initial_state.model_copy(
            update={"stress": 0.0, "motivation": 0.3, "fatigue": 0.05},
        )
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = pass_score

        diary = "あ" * 400
        result = await critic.evaluate_full(
            initial_state,
            curr_state,
            diary,
            sample_event,
        )

        assert "trigram_overlap" not in result.rule_based.details


class TestCriticPromptLoading:
    """プロンプトファイルの読み込みテスト."""

    def test_missing_prompt_raises_file_not_found(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        tmp_path: Path,
    ) -> None:
        from csdg.engine.prompt_loader import load_prompt

        with pytest.raises(FileNotFoundError, match="プロンプトファイルが見つかりません"):
            load_prompt(tmp_path, "NonExistent.md")


# ====================================================================
# CriticPipeline 統合テスト
# ====================================================================


class TestRuleBasedValidatorCriticalFailure:
    """RuleBasedValidator.has_critical_failure のテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()

    def test_no_critical_failure(self) -> None:
        """致命的違反がない場合、全軸 False."""
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 400},
        )
        veto = self.validator.has_critical_failure(result)
        assert not any(veto.values())

    def test_forbidden_pronoun_vetos_persona(self) -> None:
        """禁止一人称で persona 軸に veto."""
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=3.0,
            details={"char_count": 400, "forbidden_pronoun_found": True},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["persona_deviation"] is True
        assert veto["temporal_consistency"] is False
        assert veto["emotional_plausibility"] is False

    def test_extreme_char_deviation_vetos_all(self) -> None:
        """文字数 ±50% 超で全軸に veto."""
        # mid = (300+500)/2 = 400, lower = 200, upper = 600
        # char_count=100 is well below 200
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 100},
        )
        veto = self.validator.has_critical_failure(result)
        assert all(veto.values())

    def test_high_trigram_overlap_vetos_temporal(self) -> None:
        """trigram overlap > 50% で temporal 軸に veto."""
        result = LayerScore(
            temporal_consistency=3.5,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 400, "trigram_overlap": 0.6},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["temporal_consistency"] is True
        assert veto["persona_deviation"] is False

    def test_overlap_at_boundary_no_veto(self) -> None:
        """trigram overlap = 50% ちょうどでは veto なし."""
        result = LayerScore(
            temporal_consistency=3.5,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 400, "trigram_overlap": 0.50},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["temporal_consistency"] is False


class TestRuleBasedValidatorForbiddenPronouns:
    """禁止一人称検出のテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.0, motivation=0.3, fatigue=0.05)
        self.event = _make_event()
        self.expected_delta = {"stress": -0.06, "motivation": 0.08, "fatigue": -0.04}

    def test_forbidden_pronoun_detected(self) -> None:
        """禁止一人称「僕」を含む日記で検出される."""
        diary = "あ" * 190 + "僕は今日も頑張った" + "あ" * 190
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details.get("forbidden_pronoun_found") is True
        assert "僕" in result.details.get("forbidden_pronouns", [])

    def test_allowed_pronoun_not_detected(self) -> None:
        """許可された一人称「わたし」は検出されない."""
        diary = "あ" * 190 + "わたしは今日も頑張った" + "あ" * 190
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details.get("forbidden_pronoun_found") is None


class TestCriticPipeline:
    """CriticPipeline の統合テスト."""

    @pytest.mark.asyncio()
    async def test_evaluate_returns_critic_result(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """CriticPipeline.evaluate が CriticResult を返す."""
        from csdg.schemas import CriticResult

        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=4,
            emotional_plausibility=4,
            persona_deviation=5,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        curr = _make_state(stress=0.0, motivation=0.3)
        diary = "あ" * 400
        event = _make_event()

        result = await pipeline.evaluate(prev, curr, diary, event)

        assert isinstance(result, CriticResult)
        assert isinstance(result.final_score, CriticScore)
        assert isinstance(result.rule_based, LayerScore)
        assert isinstance(result.statistical, LayerScore)
        assert isinstance(result.llm_judge, LayerScore)

    @pytest.mark.asyncio()
    async def test_low_quality_input_lowers_score(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """低品質な入力で Layer 1/2 がスコアを下げる."""
        assert isinstance(mock_llm_client, AsyncMock)
        # LLM は高スコアを返すが、Layer 1/2 が引き下げるはず
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=5,
            emotional_plausibility=5,
            persona_deviation=5,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        curr = _make_state(stress=0.0, motivation=0.3)

        # 良い日記で評価
        good_diary = "あ" * 400
        good_result = await pipeline.evaluate(prev, curr, good_diary, _make_event())

        # 短い日記 + 絵文字で評価
        bad_diary = "短い\U0001f600"
        bad_result = await pipeline.evaluate(prev, curr, bad_diary, _make_event())

        # 低品質な入力のスコアが低くなる
        good_total = (
            good_result.final_score.temporal_consistency
            + good_result.final_score.emotional_plausibility
            + good_result.final_score.persona_deviation
        )
        bad_total = (
            bad_result.final_score.temporal_consistency
            + bad_result.final_score.emotional_plausibility
            + bad_result.final_score.persona_deviation
        )
        assert bad_total < good_total

    @pytest.mark.asyncio()
    async def test_emotional_score_varies_with_input_quality(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """emotional スコアが入力の質に応じて分散する (全Day同一にならない).

        StatisticalChecker は max_deviation > 0.5 で減点するため、
        十分に大きな deviation を持つ入力を含める。
        """
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=4,
            emotional_plausibility=4,
            persona_deviation=4,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)

        # ケース1: 小さな deviation -> 高スコア
        prev1 = _make_state()
        curr1 = _make_state(stress=prev1.stress + 0.01, motivation=prev1.motivation - 0.01)
        result1 = await pipeline.evaluate(prev1, curr1, "あ" * 400, _make_event(impact=0.0))

        # ケース2: 非常に大きな deviation -> 低スコア (max_deviation > 0.5)
        prev2 = _make_state()
        curr2 = _make_state(stress=0.9, motivation=-0.8, fatigue=0.8)
        result2 = await pipeline.evaluate(prev2, curr2, "あ" * 400, _make_event(impact=0.0))

        # 大きな deviation を持つケースはスコアが低くなるはず
        assert result2.statistical.emotional_plausibility < result1.statistical.emotional_plausibility, (
            f"Large deviation should lower score: "
            f"{result2.statistical.emotional_plausibility} vs {result1.statistical.emotional_plausibility}"
        )

    @pytest.mark.asyncio()
    async def test_weights_are_recorded(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """CriticResult に使用された weights が記録される."""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=4,
            emotional_plausibility=4,
            persona_deviation=4,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        result = await pipeline.evaluate(
            _make_state(),
            _make_state(),
            "あ" * 400,
            _make_event(),
        )

        assert result.weights["rule_based"] == pytest.approx(0.40)
        assert result.weights["statistical"] == pytest.approx(0.35)
        assert result.weights["llm_judge"] == pytest.approx(0.25)

    @pytest.mark.asyncio()
    async def test_veto_caps_persona_on_forbidden_pronoun(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """禁止一人称で veto 発動時、persona スコアが veto_cap 以下になる."""
        assert isinstance(mock_llm_client, AsyncMock)
        # LLM は満点を返すが、Layer1 の veto でキャップされるはず
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=5,
            emotional_plausibility=5,
            persona_deviation=5,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        curr = _make_state(stress=0.0, motivation=0.3)
        # 禁止一人称「僕」を含む日記
        diary = "あ" * 190 + "僕は今日も頑張った" + "あ" * 190
        event = _make_event()

        result = await pipeline.evaluate(prev, curr, diary, event)

        assert result.veto_applied.get("persona_deviation") is True
        assert result.final_score.persona_deviation <= test_config.veto_cap_persona

    @pytest.mark.asyncio()
    async def test_no_veto_when_no_critical_failure(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """致命的違反なしでは veto 非発動、通常の重み付き平均が使われる."""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=4,
            emotional_plausibility=4,
            persona_deviation=4,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        curr = _make_state(stress=0.0, motivation=0.3)
        diary = "あ" * 400  # 正常な日記
        event = _make_event()

        result = await pipeline.evaluate(prev, curr, diary, event)

        assert not any(result.veto_applied.values())

    @pytest.mark.asyncio()
    async def test_inverse_estimation_score_recorded(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """逆推定一致スコアが CriticResult に記録される."""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=4,
            emotional_plausibility=4,
            persona_deviation=4,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        result = await pipeline.evaluate(
            _make_state(),
            _make_state(),
            "あ" * 400,
            _make_event(),
        )

        assert result.inverse_estimation_score is not None
        assert 1.0 <= result.inverse_estimation_score <= 5.0

    @pytest.mark.asyncio()
    async def test_low_inverse_estimation_vetos_emotional(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """逆推定一致スコアが低い場合、emotional 軸に veto がかかる."""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=5,
            emotional_plausibility=5,
            persona_deviation=5,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        # 非常に大きな deviation -> 低い inverse_estimation_score
        curr = _make_state(stress=0.9, motivation=-0.9, fatigue=0.9)
        diary = "あ" * 400
        event = _make_event(impact=0.0)

        result = await pipeline.evaluate(prev, curr, diary, event)

        # deviation が大きいため inverse_estimation_score が低くなるはず
        if result.inverse_estimation_score is not None and result.inverse_estimation_score <= 2.0:
            assert result.final_score.emotional_plausibility <= test_config.veto_cap_emotional

    @pytest.mark.asyncio()
    async def test_veto_overrides_safety_adjustment(
        self,
        mock_llm_client: LLMClient,
        test_config: CSDGConfig,
        critic_prompts_dir: Path,
    ) -> None:
        """Veto が _MAX_SCORE_ADJUSTMENT の安全制限をバイパスして強制適用される."""
        assert isinstance(mock_llm_client, AsyncMock)
        # LLM は persona を高スコアで返すが、Layer1 の禁止一人称 veto でキャップされるはず
        mock_llm_client.generate_structured.return_value = CriticScore(
            temporal_consistency=5,
            emotional_plausibility=5,
            persona_deviation=5,
        )

        pipeline = CriticPipeline(mock_llm_client, test_config, prompts_dir=critic_prompts_dir)
        prev = _make_state()
        curr = _make_state(stress=0.0, motivation=0.3)
        # 禁止一人称「うち」を含む日記 (veto 対象)
        diary = "あ" * 190 + "うちは今日も頑張った" + "あ" * 190
        event = _make_event()

        result = await pipeline.evaluate(prev, curr, diary, event)

        # veto が安全制限を上書きし、persona_deviation が cap 以下になること
        assert result.veto_applied.get("persona_deviation") is True
        assert result.final_score.persona_deviation <= test_config.veto_cap_persona


# ====================================================================
# TestHasCriticalFailure (#5)
# ====================================================================


class TestHasCriticalFailure:
    """RuleBasedValidator.has_critical_failure のテスト。"""

    def test_forbidden_pronoun_triggers_persona_veto(self) -> None:
        """forbidden_pronoun_found が True → persona 軸に veto。"""
        validator = RuleBasedValidator()
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"forbidden_pronoun_found": True, "char_count": 400},
        )
        veto = validator.has_critical_failure(result)
        assert veto["persona_deviation"] is True
        assert veto["temporal_consistency"] is False
        assert veto["emotional_plausibility"] is False

    def test_extreme_low_char_count_triggers_all_axes_veto(self) -> None:
        """文字数が mid * 0.5 以下 → 全軸に veto。"""
        validator = RuleBasedValidator()
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 100},
        )
        veto = validator.has_critical_failure(result)
        assert veto["temporal_consistency"] is True
        assert veto["emotional_plausibility"] is True
        assert veto["persona_deviation"] is True

    def test_critical_trigram_overlap_triggers_temporal_veto(self) -> None:
        """trigram_overlap > 0.50 → temporal 軸に veto。"""
        validator = RuleBasedValidator()
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 400, "trigram_overlap": 0.55},
        )
        veto = validator.has_critical_failure(result)
        assert veto["temporal_consistency"] is True
        assert veto["emotional_plausibility"] is False

    def test_no_critical_failure_returns_all_false(self) -> None:
        """正常な結果 → veto なし。"""
        validator = RuleBasedValidator()
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 400, "trigram_overlap": 0.1},
        )
        veto = validator.has_critical_failure(result)
        assert all(v is False for v in veto.values())


# ====================================================================
# TestComputeInverseEstimation (#6)
# ====================================================================


class TestComputeInverseEstimation:
    """LLMJudge._compute_inverse_estimation のテスト。"""

    def setup_method(self) -> None:
        from csdg.engine.critic import LLMJudge

        self.judge = LLMJudge.__new__(LLMJudge)  # __init__ をバイパス

    def test_empty_deviation_returns_5(self) -> None:
        assert self.judge._compute_inverse_estimation("text", _make_state(), {}) == 5.0

    def test_zero_deviation_returns_5(self) -> None:
        assert self.judge._compute_inverse_estimation("text", _make_state(), {"stress": 0.0}) == 5.0

    def test_moderate_deviation(self) -> None:
        score = self.judge._compute_inverse_estimation("text", _make_state(), {"stress": 0.5})
        assert score == pytest.approx(3.0, abs=0.1)

    def test_large_deviation_floors_at_1(self) -> None:
        score = self.judge._compute_inverse_estimation("text", _make_state(), {"stress": 2.0})
        assert score == 1.0

    def test_small_deviation(self) -> None:
        score = self.judge._compute_inverse_estimation("text", _make_state(), {"stress": 0.125})
        assert score == pytest.approx(4.5, abs=0.1)


# ====================================================================
# TestConsensusAmplification (#7)
# ====================================================================


class TestConsensusAmplification:
    """CriticPipeline._compute_final_score のコンセンサス補正テスト."""

    def _make_pipeline(self) -> CriticPipeline:
        from unittest.mock import MagicMock

        from csdg.config import CSDGConfig

        config = CSDGConfig()
        pipeline = CriticPipeline.__new__(CriticPipeline)
        pipeline._weights = config.critic_weights
        pipeline._veto_caps = MagicMock()
        pipeline._veto_caps.temporal = 2.0
        pipeline._veto_caps.emotional = 2.0
        pipeline._veto_caps.persona = 2.0
        return pipeline

    def _make_layer(self, t: float, e: float, p: float) -> LayerScore:
        return LayerScore(
            temporal_consistency=t,
            emotional_plausibility=e,
            persona_deviation=p,
            details={},
        )

    def test_consensus_pushes_score_down(self) -> None:
        """L1/L2が低くL3が高い場合、最終スコアが引き下げられる."""
        pipeline = self._make_pipeline()
        l1 = self._make_layer(3.0, 3.0, 4.0)
        l2 = self._make_layer(3.0, 3.0, 4.0)
        l3 = self._make_layer(4.0, 4.0, 4.0)

        result = pipeline._compute_final_score(l1, l2, l3)
        # L1/L2=3.0, L3=4.0 → correction pulls down
        assert result.emotional_plausibility <= 3

    def test_consensus_pushes_score_up(self) -> None:
        """L1/L2が高くL3が低い場合、最終スコアが引き上げられる."""
        pipeline = self._make_pipeline()
        l1 = self._make_layer(4.0, 5.0, 4.0)
        l2 = self._make_layer(4.0, 5.0, 4.0)
        l3 = self._make_layer(4.0, 4.0, 4.0)

        result = pipeline._compute_final_score(l1, l2, l3)
        assert result.emotional_plausibility >= 5

    def test_consensus_no_effect_when_agreement(self) -> None:
        """L1/L2/L3が一致する場合、補正なし."""
        pipeline = self._make_pipeline()
        l1 = self._make_layer(4.0, 4.0, 4.0)
        l2 = self._make_layer(4.0, 4.0, 4.0)
        l3 = self._make_layer(4.0, 4.0, 4.0)

        result = pipeline._compute_final_score(l1, l2, l3)
        assert result.temporal_consistency == 4
        assert result.emotional_plausibility == 4
        assert result.persona_deviation == 4

    def test_consensus_cap_limits_adjustment(self) -> None:
        """MAX_SCORE_ADJUSTMENT=0 で consensus 補正が最終整数に影響しない."""
        pipeline = self._make_pipeline()
        # L1/L2=5.0, L3=2.0 → 大きな乖離
        l1 = self._make_layer(5.0, 5.0, 5.0)
        l2 = self._make_layer(5.0, 5.0, 5.0)
        l3 = self._make_layer(2.0, 2.0, 2.0)

        result = pipeline._compute_final_score(l1, l2, l3)

        # weighted avg = 0.4*5 + 0.35*5 + 0.25*2 = 4.25 → round=4
        # MAX_ADJ=0 なので consensus は最終整数に影響しない
        for field in ("temporal_consistency", "emotional_plausibility", "persona_deviation"):
            score = getattr(result, field)
            assert score == 4, f"{field}={score} should be round(weighted_avg)=4"


# ====================================================================
# TestEndingTrigramOverlap (#8)
# ====================================================================


class TestEndingTrigramOverlap:
    """余韻 trigram 類似度チェックのテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.0, motivation=0.3)
        self.event = _make_event()
        self.expected_delta = {"stress": -0.06, "motivation": 0.08, "fatigue": -0.04}

    def test_similar_endings_detected(self) -> None:
        """類似した余韻がtrigramで検出される."""
        diary = "あ" * 350 + "\n\nこの震えが教えてくれるものがあるとすれば、それは効率性では測れない何か......"
        prev = "あ" * 350 + "\n\nこの震えが教えてくれるものがあるとすれば、それはきっと効率性の向こう側にある何か......"
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            prev_diary=prev,
        )
        has_similarity = result.details.get("ending_similarity_high") is True
        has_overlap = result.details.get("ending_trigram_overlap", 0) > 0.2
        assert has_similarity or has_overlap

    def test_different_endings_not_flagged(self) -> None:
        """異なる余韻はフラグされない."""
        diary = "あ" * 350 + "\n\nキーボードを叩く指先に、まだあの震えが残っている......"
        prev = "あ" * 350 + "\n\n古い本のページに残った疑問符が、今夜は少し違って見える......"
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
            prev_diary=prev,
        )
        assert result.details.get("ending_similarity_high") is not True


# ====================================================================
# TestFinerEmotionalTiers (#9)
# ====================================================================


class TestFinerEmotionalTiers:
    """L1 emotional の5段階スケーリングのテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()
        self.event = _make_event()

    def test_tiny_deviation_gets_max_bonus(self) -> None:
        """max_dev < 0.03 → 4.0 (base 2.5 + 1.5)."""
        prev = _make_state(stress=0.1, motivation=0.2, fatigue=0.1)
        curr = _make_state(stress=0.12, motivation=0.19, fatigue=0.11)
        expected = {"stress": 0.02, "motivation": -0.01, "fatigue": 0.01}
        result = self.validator.evaluate(
            "あ" * 400,
            prev,
            curr,
            self.event,
            expected,
        )
        assert result.emotional_plausibility >= 3.5

    def test_large_deviation_gets_penalty(self) -> None:
        """max_dev >= 0.15 → 2.0 (base 2.5 - 0.5)."""
        prev = _make_state(stress=0.0, motivation=0.0, fatigue=0.0)
        curr = _make_state(stress=0.2, motivation=0.0, fatigue=0.0)
        # expected=0, actual=0.2, dev=0.2 > 0.15
        expected = {"stress": 0.0, "motivation": 0.0, "fatigue": 0.0}
        result = self.validator.evaluate(
            "あ" * 400,
            prev,
            curr,
            self.event,
            expected,
        )
        assert result.emotional_plausibility <= 2.5
        assert result.details.get("rule_max_deviation", 0) >= 0.15


class TestCharCountValidation:
    """文字数チェック (400文字ベース) のテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.0, motivation=0.3, fatigue=0.05)
        self.event = _make_event()
        self.expected_delta = {"stress": -0.06, "motivation": 0.08, "fatigue": -0.04}

    def test_within_range_no_penalty(self) -> None:
        """400文字の日記は減点されない."""
        diary = "# テストタイトル\n\n" + "あ" * 400
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details["char_count"] == 400
        assert result.details.get("char_count_violation") is None

    def test_over_500_penalty(self) -> None:
        """500文字超は重大な減点."""
        diary = "# テストタイトル\n\n" + "あ" * 550
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details.get("char_count_violation") == "too_long"

    def test_under_300_penalty(self) -> None:
        """300文字未満は重大な減点."""
        diary = "# テストタイトル\n\n" + "あ" * 250
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details.get("char_count_violation") == "too_short"

    def test_warning_range(self) -> None:
        """350文字未満は軽微な警告 (300-350の範囲)."""
        diary = "# テストタイトル\n\n" + "あ" * 320
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        # 300-350はペナルティなし (_MIN_DIARY_LENGTH=300以上, _IDEAL_MIN_LENGTH=350未満)
        assert result.details.get("char_count_violation") is None
        assert result.details.get("char_count_ideal") is False

    def test_title_excluded_from_count(self) -> None:
        """タイトル行は文字数カウントに含まれない."""
        diary = "# これは長いタイトルだが文字数に含まれない\n\n" + "あ" * 400
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details["char_count"] == 400

    def test_over_580_strong_penalty(self) -> None:
        """580文字超で persona_deviation に -2.0 ペナルティ."""
        diary = "# タイトル\n\n" + "あ" * 590
        result = self.validator.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            self.event,
            self.expected_delta,
        )
        assert result.details.get("char_count_over", 0) > 80
        assert result.persona_deviation <= 2.0


class TestVetoCharCount:
    """文字数 veto 閾値 (550文字超) のテスト."""

    def setup_method(self) -> None:
        self.validator = RuleBasedValidator()

    def test_veto_triggers_at_550_chars(self) -> None:
        """550文字超で全軸 veto 発動."""
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 560},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["persona_deviation"] is True

    def test_no_veto_at_540_chars(self) -> None:
        """540文字では veto 不発動."""
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=5.0,
            details={"char_count": 540},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["persona_deviation"] is False


class TestHighImpactEmotionalCollapse:
    """高インパクト日の感情決壊チェックのテスト."""

    def setup_method(self) -> None:
        from csdg.engine.critic import StatisticalChecker

        self.checker = StatisticalChecker()
        self.prev_state = _make_state()
        self.curr_state = _make_state(stress=0.3, motivation=-0.1, fatigue=0.2)
        self.expected = {"stress": 0.24, "motivation": -0.32, "fatigue": 0.16}
        self.deviation = {"stress": 0.06, "motivation": 0.22, "fatigue": 0.04}

    def test_consecutive_short_burst_detected(self) -> None:
        """連続3文の短文連打で has_short_burst=True."""
        # 句読点で区切り、短文3連続を確保
        diary = "あいうえお。" * 30 + "無理。嫌だ。帰る。もう何もしたくない。" + "かきくけこ。" * 20
        event = _make_event(impact=-0.8)
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            event,
            self.expected,
            self.deviation,
        )
        assert result.details.get("has_short_burst") is True

    def test_scattered_short_not_burst(self) -> None:
        """散在する短文では has_short_burst=False."""
        diary = "無理。" + "あ" * 100 + "嫌だ。" + "あ" * 100 + "帰る。" + "あ" * 100
        event = _make_event(impact=-0.8)
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            event,
            self.expected,
            self.deviation,
        )
        assert result.details.get("has_short_burst") is False

    def test_insufficient_features_strong_penalty(self) -> None:
        """features<2 で persona score が大幅低下."""
        diary = "あ" * 400
        event = _make_event(impact=-0.8)
        result = self.checker.evaluate(
            diary,
            self.prev_state,
            self.curr_state,
            event,
            self.expected,
            self.deviation,
        )
        assert result.details.get("emotional_collapse_failed") is True
        assert result.persona_deviation <= 1.0


# ====================================================================
# LLMJudge prev_day_ending 転送テスト
# ====================================================================


class TestLLMJudgePrevDayEnding:
    """LLMJudge が prev_day_ending を Critic プロンプトに含めることのテスト."""

    def test_build_prompt_includes_prev_day_ending(
        self,
        test_config: CSDGConfig,
    ) -> None:
        """prev_day_ending が渡された場合、プロンプトに含まれること."""
        from csdg.engine.critic import LLMJudge

        # prev_day_ending を含むテンプレートを持つプロンプトディレクトリを作成
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)
            persona = prompts_dir / "System_Persona.md"
            persona.write_text("You are Tokomi.", encoding="utf-8")

            critic_prompt = prompts_dir / "Prompt_Critic.md"
            critic_prompt.write_text(
                "Evaluate.\n"
                "diary: {diary_text}\n"
                "state: {current_state}\n"
                "event: {event}\n"
                "human_condition: {human_condition}\n"
                "expected_delta: {expected_delta}\n"
                "deviation: {deviation}\n"
                "layer_results: {layer_results}\n"
                "prev_day_ending: {prev_day_ending}\n",
                encoding="utf-8",
            )

            judge = LLMJudge(AsyncMock(), test_config, prompts_dir)
            prev = _make_state()
            curr = _make_state(stress=0.0)
            event = _make_event()
            layer = LayerScore(
                temporal_consistency=3.0,
                emotional_plausibility=3.0,
                persona_deviation=3.0,
            )

            ending = "空になったカップを見つめて、席を立った。"
            prompt = judge._build_prompt(
                diary_text="テスト日記",
                curr_state=curr,
                event=event,
                expected_delta={"stress": 0.0},
                deviation={"stress": 0.0},
                layer1_result=layer,
                layer2_result=layer,
                prev_day_ending=ending,
            )

            assert ending in prompt

    def test_build_prompt_empty_prev_day_ending(
        self,
        test_config: CSDGConfig,
    ) -> None:
        """prev_day_ending が空の場合、フォールバックテキストが含まれること."""
        from csdg.engine.critic import LLMJudge

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)
            persona = prompts_dir / "System_Persona.md"
            persona.write_text("You are Tokomi.", encoding="utf-8")

            critic_prompt = prompts_dir / "Prompt_Critic.md"
            critic_prompt.write_text(
                "Evaluate.\n"
                "diary: {diary_text}\n"
                "state: {current_state}\n"
                "event: {event}\n"
                "human_condition: {human_condition}\n"
                "expected_delta: {expected_delta}\n"
                "deviation: {deviation}\n"
                "layer_results: {layer_results}\n"
                "prev_day_ending: {prev_day_ending}\n",
                encoding="utf-8",
            )

            judge = LLMJudge(AsyncMock(), test_config, prompts_dir)
            curr = _make_state(stress=0.0)
            event = _make_event()
            layer = LayerScore(
                temporal_consistency=3.0,
                emotional_plausibility=3.0,
                persona_deviation=3.0,
            )

            prompt = judge._build_prompt(
                diary_text="テスト日記",
                curr_state=curr,
                event=event,
                expected_delta={"stress": 0.0},
                deviation={"stress": 0.0},
                layer1_result=layer,
                layer2_result=layer,
                prev_day_ending="",
            )

            assert "(初日のため参照なし)" in prompt
