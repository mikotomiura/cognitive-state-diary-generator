"""csdg/config.py のテスト。

CSDGConfig のデフォルト値・プロパティ・環境変数読み込みを検証する。
test-standards/SKILL.md の AAA パターンおよび命名規約に従う。
"""

from __future__ import annotations

import math

import pytest

from csdg.config import CriticWeights, CSDGConfig, StateTransitionConfig, VetoCaps


@pytest.fixture()
def config(monkeypatch: pytest.MonkeyPatch) -> CSDGConfig:
    """APIキーを設定した CSDGConfig インスタンスを返す。"""
    monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
    return CSDGConfig()


class TestCSDGConfigDefaults:
    """CSDGConfig のデフォルト値テスト。"""

    def test_llm_model_default(self, config: CSDGConfig) -> None:
        """llm_model のデフォルト値が claude-sonnet-4-20250514 である。"""
        assert config.llm_model == "claude-sonnet-4-20250514"

    def test_llm_base_url_default(self, config: CSDGConfig) -> None:
        """llm_base_url のデフォルト値が正しい。"""
        assert config.llm_base_url == "https://api.anthropic.com"

    def test_max_retries_default(self, config: CSDGConfig) -> None:
        """max_retries のデフォルト値が 3 である。"""
        assert config.max_retries == 3

    def test_initial_temperature_default(self, config: CSDGConfig) -> None:
        """initial_temperature のデフォルト値が 0.7 である。"""
        assert config.initial_temperature == 0.7

    def test_temperature_decay_step_default(self, config: CSDGConfig) -> None:
        """temperature_decay_step のデフォルト値が 0.2 である。"""
        assert config.temperature_decay_step == 0.2

    def test_memory_window_size_default(self, config: CSDGConfig) -> None:
        """memory_window_size のデフォルト値が 3 である。"""
        assert config.memory_window_size == 3

    def test_emotion_sensitivity_stress_default(self, config: CSDGConfig) -> None:
        """emotion_sensitivity_stress のデフォルト値が -0.3 である。"""
        assert config.emotion_sensitivity_stress == -0.3

    def test_emotion_sensitivity_motivation_default(self, config: CSDGConfig) -> None:
        """emotion_sensitivity_motivation のデフォルト値が 0.4 である。"""
        assert config.emotion_sensitivity_motivation == 0.4

    def test_emotion_sensitivity_fatigue_default(self, config: CSDGConfig) -> None:
        """emotion_sensitivity_fatigue のデフォルト値が -0.2 である。"""
        assert config.emotion_sensitivity_fatigue == -0.2

    def test_output_dir_default(self, config: CSDGConfig) -> None:
        """output_dir のデフォルト値が output である。"""
        assert config.output_dir == "output"


class TestEmotionSensitivityProperty:
    """emotion_sensitivity プロパティのテスト。"""

    def test_returns_correct_dict(self, config: CSDGConfig) -> None:
        """emotion_sensitivity が正しい辞書を返す。"""
        expected = {
            "stress": -0.3,
            "motivation": 0.4,
            "fatigue": -0.2,
        }
        assert config.emotion_sensitivity == expected

    def test_keys(self, config: CSDGConfig) -> None:
        """emotion_sensitivity のキーが stress, motivation, fatigue である。"""
        assert set(config.emotion_sensitivity.keys()) == {"stress", "motivation", "fatigue"}

    def test_custom_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """カスタム感情感度係数が反映される。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_EMOTION_SENSITIVITY_STRESS", "-0.5")
        monkeypatch.setenv("CSDG_EMOTION_SENSITIVITY_MOTIVATION", "0.8")
        monkeypatch.setenv("CSDG_EMOTION_SENSITIVITY_FATIGUE", "-0.1")
        cfg = CSDGConfig()
        assert cfg.emotion_sensitivity == {
            "stress": -0.5,
            "motivation": 0.8,
            "fatigue": -0.1,
        }


class TestTemperatureScheduleProperty:
    """temperature_schedule プロパティのテスト。"""

    def test_default_schedule_exponential(self, config: CSDGConfig) -> None:
        """デフォルト設定で指数減衰スケジュールを返す。"""
        schedule = config.temperature_schedule
        # 初回は initial_temperature
        assert schedule[0] == pytest.approx(0.7)
        # 最終は temperature_final に近づく (指数減衰)
        assert schedule[-1] >= config.temperature_final
        # 単調減少
        for i in range(len(schedule) - 1):
            assert schedule[i] >= schedule[i + 1]

    def test_schedule_length(self, config: CSDGConfig) -> None:
        """スケジュールの長さが max_retries と一致する。"""
        assert len(config.temperature_schedule) == config.max_retries

    def test_custom_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_retries を変更するとスケジュールの長さが変わる。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_MAX_RETRIES", "5")
        cfg = CSDGConfig()
        assert len(cfg.temperature_schedule) == 5
        assert cfg.temperature_schedule[0] == pytest.approx(0.7)

    def test_exponential_lower_than_linear_at_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指数減衰が線形より終盤で低い値になることの検証。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_MAX_RETRIES", "5")
        cfg = CSDGConfig()

        exp_schedule = cfg.temperature_schedule
        # 同じパラメータで線形スケジュールを計算
        linear_schedule = [
            cfg.initial_temperature - (cfg.initial_temperature - cfg.temperature_final) * i / (cfg.max_retries - 1)
            for i in range(cfg.max_retries)
        ]

        # 中間〜終盤で指数が線形以下 (指数は急速に減衰するため)
        # 最終要素は両方とも final に近いが、中間要素で差が出る
        assert exp_schedule[1] <= linear_schedule[1]

    def test_exponential_formula_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指数減衰の計算式が正しいことの検証。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_TEMPERATURE_DECAY_CONSTANT", "1.5")
        cfg = CSDGConfig()

        schedule = cfg.temperature_schedule
        for i, temp in enumerate(schedule):
            expected = cfg.temperature_final + (cfg.initial_temperature - cfg.temperature_final) * math.exp(-1.5 * i)
            assert temp == pytest.approx(expected)


class TestEnvironmentVariables:
    """環境変数からの値読み込みテスト。"""

    def test_api_key_from_env(self, config: CSDGConfig) -> None:
        """環境変数から llm_api_key が読み込まれる。"""
        assert config.llm_api_key == "test-api-key"

    def test_custom_model_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数から llm_model が読み込まれる。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_LLM_MODEL", "claude-sonnet-4-6")
        cfg = CSDGConfig()
        assert cfg.llm_model == "claude-sonnet-4-6"

    def test_custom_output_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数から output_dir が読み込まれる。"""
        monkeypatch.setenv("CSDG_LLM_API_KEY", "test-api-key")
        monkeypatch.setenv("CSDG_OUTPUT_DIR", "/tmp/csdg_output")
        cfg = CSDGConfig()
        assert cfg.output_dir == "/tmp/csdg_output"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CSDG_LLM_API_KEY が未設定の場合エラーが発生する。"""
        monkeypatch.delenv("CSDG_LLM_API_KEY", raising=False)
        with pytest.raises((ValueError, KeyError)):
            CSDGConfig(_env_file=None)  # type: ignore[call-arg]


# ====================================================================
# 派生プロパティのテスト (#15)
# ====================================================================


class TestCriticWeightsProperty:
    """critic_weights プロパティのテスト。"""

    def test_returns_critic_weights_instance(self, config: CSDGConfig) -> None:
        weights = config.critic_weights
        assert isinstance(weights, CriticWeights)
        assert weights.rule_based == 0.3
        assert weights.statistical == 0.2
        assert weights.llm_judge == 0.5


class TestVetoCapsProperty:
    """veto_caps プロパティのテスト。"""

    def test_returns_veto_caps_instance(self, config: CSDGConfig) -> None:
        caps = config.veto_caps
        assert isinstance(caps, VetoCaps)
        assert caps.persona == 2.0
        assert caps.temporal == 2.0


class TestStateTransitionProperty:
    """state_transition プロパティのテスト。"""

    def test_returns_state_transition_config(self, config: CSDGConfig) -> None:
        st = config.state_transition
        assert isinstance(st, StateTransitionConfig)
        assert st.decay_rate == 0.1
        assert st.event_weight == 0.6


class TestApiKeyExcluded:
    """llm_api_key が model_dump から除外されることのテスト。"""

    def test_api_key_excluded_from_dump(self, config: CSDGConfig) -> None:
        dumped = config.model_dump()
        assert "llm_api_key" not in dumped
