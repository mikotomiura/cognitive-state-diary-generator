"""csdg/engine/state_transition.py のテスト。

決定論的な状態遷移関数の動作検証。LLM モック不要の純粋関数テスト。
"""

from __future__ import annotations

import pytest

from csdg.config import StateTransitionConfig
from csdg.engine.state_transition import compute_event_impact, compute_next_state
from csdg.schemas import CharacterState, DailyEvent, EmotionalDelta


# ====================================================================
# フィクスチャ
# ====================================================================


@pytest.fixture()
def base_state() -> CharacterState:
    """テスト用初期状態。"""
    return CharacterState(
        fatigue=0.1,
        motivation=0.2,
        stress=-0.1,
        current_focus="テスト",
        growth_theme="テストテーマ",
        memory_buffer=[],
        relationships={},
    )


@pytest.fixture()
def config() -> StateTransitionConfig:
    """テスト用の状態遷移設定。"""
    return StateTransitionConfig(
        decay_rate=0.1,
        event_weight=0.6,
        llm_weight=0.3,
        noise_scale=0.0,  # テストでは決定論的にする
    )


@pytest.fixture()
def sensitivity() -> dict[str, float]:
    """テスト用の感情感度係数。"""
    return {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2}


@pytest.fixture()
def neutral_event() -> DailyEvent:
    """neutral イベント (impact=+0.2)。"""
    return DailyEvent(
        day=1,
        event_type="neutral",
        domain="仕事",
        description="社内ツールの自動化スクリプトが完成し、30分かかっていた作業が2分に短縮された",
        emotional_impact=0.2,
    )


@pytest.fixture()
def high_negative_event() -> DailyEvent:
    """高インパクト negative イベント (impact=-0.9)。"""
    return DailyEvent(
        day=4,
        event_type="negative",
        domain="仕事",
        description="全社会議で経営陣が全業務のAI自動化ロードマップを発表した",
        emotional_impact=-0.9,
    )


# ====================================================================
# compute_event_impact のテスト
# ====================================================================


class TestComputeEventImpact:
    """compute_event_impact のテスト。"""

    def test_positive_impact(self, neutral_event: DailyEvent, sensitivity: dict[str, float]) -> None:
        """positive イベントで期待通りの impact が算出される。"""
        result = compute_event_impact(neutral_event, sensitivity)

        assert result.stress == pytest.approx(0.2 * -0.3)
        assert result.motivation == pytest.approx(0.2 * 0.4)
        assert result.fatigue == pytest.approx(0.2 * -0.2)

    def test_high_negative_impact(self, high_negative_event: DailyEvent, sensitivity: dict[str, float]) -> None:
        """高インパクト negative イベントの計算。"""
        result = compute_event_impact(high_negative_event, sensitivity)

        assert result.stress == pytest.approx(-0.9 * -0.3)
        assert result.motivation == pytest.approx(-0.9 * 0.4)
        assert result.fatigue == pytest.approx(-0.9 * -0.2)

    def test_zero_impact(self, sensitivity: dict[str, float]) -> None:
        """impact=0.0 で全パラメータ 0。"""
        event = DailyEvent(
            day=1,
            event_type="neutral",
            domain="内省",
            description="特に何も起きなかった平穏な一日だった",
            emotional_impact=0.0,
        )
        result = compute_event_impact(event, sensitivity)

        assert result.stress == pytest.approx(0.0)
        assert result.motivation == pytest.approx(0.0)
        assert result.fatigue == pytest.approx(0.0)


# ====================================================================
# compute_next_state のテスト
# ====================================================================


class TestComputeNextState:
    """compute_next_state のテスト。"""

    def test_event_impact_larger_means_larger_change(
        self,
        base_state: CharacterState,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
    ) -> None:
        """event_impact が大きい場合に状態変化が大きくなる。"""
        zero_delta = EmotionalDelta()

        small_event = DailyEvent(
            day=1,
            event_type="neutral",
            domain="仕事",
            description="特に何も起きなかった平穏な一日だった",
            emotional_impact=0.1,
        )
        large_event = DailyEvent(
            day=1,
            event_type="negative",
            domain="仕事",
            description="全社会議で経営陣が全業務のAI自動化ロードマップを発表した",
            emotional_impact=-0.9,
        )

        small_result = compute_next_state(base_state, small_event, zero_delta, config, sensitivity, seed=42)
        large_result = compute_next_state(base_state, large_event, zero_delta, config, sensitivity, seed=42)

        # stress の変化量を比較（large event の方が変化が大きい）
        small_stress_delta = abs(small_result.stress - base_state.stress)
        large_stress_delta = abs(large_result.stress - base_state.stress)
        assert large_stress_delta > small_stress_delta

    def test_decay_rate_recovery(
        self,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
    ) -> None:
        """decay_rate による自然回復の検証。"""
        stressed_state = CharacterState(
            fatigue=0.8,
            motivation=-0.5,
            stress=0.9,
            current_focus="テスト",
            growth_theme="テストテーマ",
        )
        zero_event = DailyEvent(
            day=1,
            event_type="neutral",
            domain="内省",
            description="特に何も起きなかった平穏な一日だった",
            emotional_impact=0.0,
        )
        zero_delta = EmotionalDelta()

        result = compute_next_state(stressed_state, zero_event, zero_delta, config, sensitivity, seed=42)

        # decay により絶対値が減少する
        assert abs(result.stress) < abs(stressed_state.stress)
        assert abs(result.fatigue) < abs(stressed_state.fatigue)

    def test_clamp_range(
        self,
        base_state: CharacterState,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
    ) -> None:
        """clamp_range を超えないことの検証。"""
        extreme_delta = EmotionalDelta(fatigue=10.0, motivation=-10.0, stress=10.0)
        event = DailyEvent(
            day=1,
            event_type="negative",
            domain="仕事",
            description="全社会議で経営陣が全業務のAI自動化ロードマップを発表した",
            emotional_impact=-1.0,
        )

        result = compute_next_state(base_state, event, extreme_delta, config, sensitivity, seed=42)

        assert -1.0 <= result.fatigue <= 1.0
        assert -1.0 <= result.motivation <= 1.0
        assert -1.0 <= result.stress <= 1.0

    def test_llm_delta_zero_still_produces_valid_transition(
        self,
        base_state: CharacterState,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """LLM delta が 0 でも決定論的部分だけで妥当な遷移になる。"""
        zero_delta = EmotionalDelta()

        result = compute_next_state(base_state, neutral_event, zero_delta, config, sensitivity, seed=42)

        # 遷移は起きている（prev_state と完全一致ではない）
        assert result.stress != base_state.stress or result.motivation != base_state.motivation

    def test_reproducibility_with_zero_noise(
        self,
        base_state: CharacterState,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """noise_scale=0 の場合に同一入力で完全一致する（再現性テスト）。"""
        config_no_noise = StateTransitionConfig(noise_scale=0.0)
        delta = EmotionalDelta(fatigue=0.1, motivation=-0.05, stress=0.2)

        result1 = compute_next_state(base_state, neutral_event, delta, config_no_noise, sensitivity)
        result2 = compute_next_state(base_state, neutral_event, delta, config_no_noise, sensitivity)

        assert result1.fatigue == pytest.approx(result2.fatigue)
        assert result1.motivation == pytest.approx(result2.motivation)
        assert result1.stress == pytest.approx(result2.stress)

    def test_reproducibility_with_same_seed(
        self,
        base_state: CharacterState,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """同一 seed で同一結果になる（ノイズありでも再現可能）。"""
        # config has default noise_scale=0, use one with noise
        noisy_config = StateTransitionConfig(noise_scale=0.05)
        delta = EmotionalDelta(fatigue=0.1, motivation=-0.05, stress=0.2)

        result1 = compute_next_state(base_state, neutral_event, delta, noisy_config, sensitivity, seed=123)
        result2 = compute_next_state(base_state, neutral_event, delta, noisy_config, sensitivity, seed=123)

        assert result1.fatigue == pytest.approx(result2.fatigue)
        assert result1.motivation == pytest.approx(result2.motivation)
        assert result1.stress == pytest.approx(result2.stress)

    def test_max_llm_delta_clips_large_delta(
        self,
        base_state: CharacterState,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """max_llm_delta を超える delta が clip される。"""
        config_with_clip = StateTransitionConfig(
            noise_scale=0.0,
            max_llm_delta=0.3,
        )
        large_delta = EmotionalDelta(fatigue=0.8, motivation=-0.8, stress=0.8)
        capped_delta = EmotionalDelta(fatigue=0.3, motivation=-0.3, stress=0.3)

        result_large = compute_next_state(base_state, neutral_event, large_delta, config_with_clip, sensitivity)
        result_capped = compute_next_state(base_state, neutral_event, capped_delta, config_with_clip, sensitivity)

        # large_delta は clip されるので capped_delta と同一結果
        assert result_large.fatigue == pytest.approx(result_capped.fatigue)
        assert result_large.motivation == pytest.approx(result_capped.motivation)
        assert result_large.stress == pytest.approx(result_capped.stress)

    def test_max_llm_delta_within_range_not_clipped(
        self,
        base_state: CharacterState,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """max_llm_delta 以内の delta は clip されない。"""
        config_with_clip = StateTransitionConfig(
            noise_scale=0.0,
            max_llm_delta=0.5,
        )
        small_delta = EmotionalDelta(fatigue=0.2, motivation=-0.1, stress=0.3)

        # max_llm_delta=0.5 なので 0.2, -0.1, 0.3 はすべて範囲内
        # clip なしの config でも同じ結果になるはず
        config_no_clip = StateTransitionConfig(
            noise_scale=0.0,
            max_llm_delta=10.0,  # 実質無制限
        )
        result_clipped = compute_next_state(base_state, neutral_event, small_delta, config_with_clip, sensitivity)
        result_unclipped = compute_next_state(base_state, neutral_event, small_delta, config_no_clip, sensitivity)

        assert result_clipped.fatigue == pytest.approx(result_unclipped.fatigue)
        assert result_clipped.motivation == pytest.approx(result_unclipped.motivation)
        assert result_clipped.stress == pytest.approx(result_unclipped.stress)

    def test_clip_then_llm_weight_applied(
        self,
        base_state: CharacterState,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """clip 後に llm_weight が正しく乗算される。"""
        config_clip = StateTransitionConfig(
            decay_rate=0.0,
            event_weight=0.0,
            llm_weight=0.5,
            noise_scale=0.0,
            max_llm_delta=0.2,
        )
        # delta=1.0 → clip to 0.2 → * 0.5 = 0.1
        delta = EmotionalDelta(fatigue=1.0, motivation=0.0, stress=0.0)
        zero_event = DailyEvent(
            day=1,
            event_type="neutral",
            domain="内省",
            description="特に何も起きなかった平穏な一日だった",
            emotional_impact=0.0,
        )

        result = compute_next_state(base_state, zero_event, delta, config_clip, sensitivity)

        # base = prev * (1 - 0) + 0 * 0 = prev = 0.1 (fatigue)
        # result = 0.1 + 0.2 * 0.5 = 0.2
        assert result.fatigue == pytest.approx(0.2)

    def test_discrete_variables_preserved(
        self,
        base_state: CharacterState,
        config: StateTransitionConfig,
        sensitivity: dict[str, float],
        neutral_event: DailyEvent,
    ) -> None:
        """離散変数 (current_focus 等) は prev_state から引き継がれる。"""
        delta = EmotionalDelta()

        result = compute_next_state(base_state, neutral_event, delta, config, sensitivity, seed=42)

        assert result.current_focus == base_state.current_focus
        assert result.growth_theme == base_state.growth_theme
        assert result.memory_buffer == base_state.memory_buffer
        assert result.relationships == base_state.relationships
