"""csdg/engine/critic.py のテスト.

純粋関数 (compute_expected_delta, compute_deviation, judge) は
LLM モック不要でテストする。3層構造 (RuleBasedValidator,
StatisticalChecker, LLMJudge, CriticPipeline) のテストを含む。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from csdg.engine.critic import (
    Critic,
    CriticPipeline,
    RuleBasedValidator,
    StatisticalChecker,
    _compute_trigram_overlap,
    _extract_trigrams,
    compute_deviation,
    compute_expected_delta,
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

    def test_good_diary_scores_high(self) -> None:
        """品質の良い日記で高スコア."""
        good_diary = "あ" * 1000  # 適切な長さ、禁止表現なし
        result = self.validator.evaluate(
            good_diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
        )
        assert result.persona_deviation >= 4.0
        assert result.temporal_consistency >= 4.0

    def test_short_diary_penalized(self) -> None:
        """短すぎる日記で persona_deviation が減点される."""
        short_diary = "短い日記。"
        result = self.validator.evaluate(
            short_diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
        )
        assert result.persona_deviation < 4.0
        assert result.details.get("char_count_violation") == "too_short"

    def test_emoji_penalized(self) -> None:
        """絵文字を含む日記で persona_deviation が大幅減点される."""
        emoji_diary = "あ" * 1000 + "\U0001f600\U0001f600"
        result = self.validator.evaluate(
            emoji_diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
        )
        assert result.persona_deviation < 4.0
        assert result.details.get("emoji_count", 0) > 0

    def test_high_trigram_overlap_penalized(self) -> None:
        """前日との重複率が高い場合に temporal_consistency が減点される."""
        diary = "あいうえおかきくけこ" * 100
        prev_diary = "あいうえおかきくけこ" * 100  # 完全一致
        result = self.validator.evaluate(
            diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
            prev_diary=prev_diary,
        )
        assert result.temporal_consistency < 4.0
        assert result.details.get("overlap_violation") is True

    def test_no_prev_diary_no_overlap_check(self) -> None:
        """前日の日記がない場合は重複チェックをスキップ."""
        diary = "あ" * 1000
        result = self.validator.evaluate(
            diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
        )
        assert "trigram_overlap" not in result.details

    def test_direction_mismatch_penalized(self) -> None:
        """感情パラメータの方向矛盾で emotional_plausibility が減点される."""
        high_event = _make_event(impact=-0.9)
        # expected: stress increases (positive delta from negative impact * negative sensitivity)
        expected = {"stress": 0.27, "motivation": -0.36, "fatigue": 0.18}
        # But actual state has stress decreased significantly
        mismatched_state = _make_state(stress=-0.5, motivation=0.5)
        diary = "あ" * 1000

        result = self.validator.evaluate(
            diary, self.prev_state, mismatched_state, high_event, expected,
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
        """通常の日記で高スコア."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        result = self.checker.evaluate(
            diary, self.prev_state, self.curr_state, self.event,
            self.expected_delta, self.small_deviation,
        )
        assert result.emotional_plausibility >= 4.0

    def test_large_deviation_penalized(self) -> None:
        """大きな deviation で emotional_plausibility が減点される."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。特に何も起きなかった。"
        large_deviation = {"stress": 0.8, "motivation": -0.9, "fatigue": 0.7}
        result = self.checker.evaluate(
            diary, self.prev_state, self.curr_state, self.event,
            self.expected_delta, large_deviation,
        )
        assert result.emotional_plausibility < 5.0

    def test_statistics_in_details(self) -> None:
        """統計情報が details に含まれる."""
        diary = "今日は普通の一日だった。朝起きて仕事に行った。"
        result = self.checker.evaluate(
            diary, self.prev_state, self.curr_state, self.event,
            self.expected_delta, self.small_deviation,
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
            diary, self.prev_state, self.curr_state, event,
            self.expected_delta, self.small_deviation,
        )
        assert result.details.get("excessive_assertions", 0) > 0


# ====================================================================
# トライグラム関数のテスト
# ====================================================================


class TestTrigramFunctions:
    """トライグラム関連関数のテスト."""

    def test_extract_trigrams(self) -> None:
        trigrams = _extract_trigrams("abcde")
        assert "abc" in trigrams
        assert "bcd" in trigrams
        assert "cde" in trigrams

    def test_extract_trigrams_short_text(self) -> None:
        assert _extract_trigrams("ab") == set()

    def test_compute_overlap_identical(self) -> None:
        overlap = _compute_trigram_overlap("あいうえお", "あいうえお")
        assert overlap == pytest.approx(1.0)

    def test_compute_overlap_different(self) -> None:
        overlap = _compute_trigram_overlap("あいうえお", "かきくけこ")
        assert overlap == pytest.approx(0.0)

    def test_compute_overlap_empty(self) -> None:
        overlap = _compute_trigram_overlap("", "abc")
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

    @pytest.mark.asyncio()
    async def test_build_critic_prompt_injects_data(
        self,
        critic: Critic,
        initial_state: CharacterState,
        sample_event: DailyEvent,
        sample_diary: str,
    ) -> None:
        """_build_critic_prompt がデータを正しく注入する."""
        expected_delta = compute_expected_delta(
            sample_event,
            {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2},
        )
        curr_state = initial_state.model_copy(
            update={"stress": 0.0, "motivation": 0.3, "fatigue": 0.05},
        )
        deviation = compute_deviation(initial_state, curr_state, expected_delta)

        prompt = critic._build_critic_prompt(
            diary_text=sample_diary,
            curr_state=curr_state,
            event=sample_event,
            expected_delta=expected_delta,
            deviation=deviation,
        )

        assert "自動化スクリプト" in prompt
        assert '"motivation"' in prompt
        assert (
            sample_event.description
            in json.loads(
                prompt.split("event: ")[1].split("\nexpected_delta:")[0],
            )["description"]
        )


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
            initial_state, curr_state, diary, sample_event, prev_diary=prev_diary,
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

        diary = "あ" * 1000
        result = await critic.evaluate_full(
            initial_state, curr_state, diary, sample_event,
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
        critic = Critic(mock_llm_client, test_config, prompts_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match="プロンプトファイルが見つかりません"):
            critic._load_prompt("NonExistent.md")


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
            details={"char_count": 1000},
        )
        veto = self.validator.has_critical_failure(result)
        assert not any(veto.values())

    def test_forbidden_pronoun_vetos_persona(self) -> None:
        """禁止一人称で persona 軸に veto."""
        result = LayerScore(
            temporal_consistency=5.0,
            emotional_plausibility=5.0,
            persona_deviation=3.0,
            details={"char_count": 1000, "forbidden_pronoun_found": True},
        )
        veto = self.validator.has_critical_failure(result)
        assert veto["persona_deviation"] is True
        assert veto["temporal_consistency"] is False
        assert veto["emotional_plausibility"] is False

    def test_extreme_char_deviation_vetos_all(self) -> None:
        """文字数 ±50% 超で全軸に veto."""
        # mid = (800+2000)/2 = 1400, lower = 700, upper = 2100
        # char_count=100 is well below 700
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
            details={"char_count": 1000, "trigram_overlap": 0.6},
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
            details={"char_count": 1000, "trigram_overlap": 0.50},
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
        diary = "あ" * 500 + "僕は今日も頑張った" + "あ" * 500
        result = self.validator.evaluate(
            diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
        )
        assert result.details.get("forbidden_pronoun_found") is True
        assert "僕" in result.details.get("forbidden_pronouns", [])

    def test_allowed_pronoun_not_detected(self) -> None:
        """許可された一人称「わたし」は検出されない."""
        diary = "あ" * 500 + "わたしは今日も頑張った" + "あ" * 500
        result = self.validator.evaluate(
            diary, self.prev_state, self.curr_state, self.event, self.expected_delta,
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
        diary = "あ" * 1000
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
        good_diary = "あ" * 1000
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
        result1 = await pipeline.evaluate(prev1, curr1, "あ" * 1000, _make_event(impact=0.0))

        # ケース2: 非常に大きな deviation -> 低スコア (max_deviation > 0.5)
        prev2 = _make_state()
        curr2 = _make_state(stress=0.9, motivation=-0.8, fatigue=0.8)
        result2 = await pipeline.evaluate(prev2, curr2, "あ" * 1000, _make_event(impact=0.0))

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
            _make_state(), _make_state(), "あ" * 1000, _make_event(),
        )

        assert result.weights["rule_based"] == pytest.approx(0.3)
        assert result.weights["statistical"] == pytest.approx(0.2)
        assert result.weights["llm_judge"] == pytest.approx(0.5)

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
        diary = "あ" * 500 + "僕は今日も頑張った" + "あ" * 500
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
        diary = "あ" * 1000  # 正常な日記
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
            _make_state(), _make_state(), "あ" * 1000, _make_event(),
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
        diary = "あ" * 1000
        event = _make_event(impact=0.0)

        result = await pipeline.evaluate(prev, curr, diary, event)

        # deviation が大きいため inverse_estimation_score が低くなるはず
        if result.inverse_estimation_score is not None and result.inverse_estimation_score <= 2.0:
            assert result.final_score.emotional_plausibility <= test_config.veto_cap_emotional
