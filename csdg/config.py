"""設定管理モジュール。

環境変数または .env ファイルからパイプライン設定を読み込む。
architecture.md §5.2 および functional-design.md §5.4 の仕様に準拠する。
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class CriticWeights(BaseModel):
    """Critic 3層分解の重み設定。"""

    rule_based: float = 0.3
    statistical: float = 0.2
    llm_judge: float = 0.5


class StateTransitionConfig(BaseModel):
    """状態遷移の半数式化設定。

    決定論的骨格 + LLM delta 補正 + 微小ノイズの重みを制御する。
    """

    decay_rate: float = 0.1
    event_weight: float = 0.6
    llm_weight: float = 0.3
    noise_scale: float = 0.05
    clamp_min: float = -1.0
    clamp_max: float = 1.0


class CSDGConfig(BaseSettings):
    """CSDG パイプライン設定。

    環境変数のプレフィックス ``CSDG_`` から各フィールドを読み込む。
    例: ``CSDG_LLM_API_KEY``, ``CSDG_LLM_MODEL`` など。
    """

    model_config = {"env_prefix": "CSDG_", "env_file": ".env", "env_file_encoding": "utf-8"}

    # LLM設定
    llm_api_key: str
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

    # Critic 重み設定
    critic_weight_rule_based: float = 0.3
    critic_weight_statistical: float = 0.2
    critic_weight_llm_judge: float = 0.5

    # 状態遷移設定
    state_transition_decay_rate: float = 0.1
    state_transition_event_weight: float = 0.6
    state_transition_llm_weight: float = 0.3
    state_transition_noise_scale: float = 0.05

    # 出力
    output_dir: str = "output"

    @property
    def emotion_sensitivity(self) -> dict[str, float]:
        """感情感度係数を辞書形式で返す。"""
        return {
            "stress": self.emotion_sensitivity_stress,
            "motivation": self.emotion_sensitivity_motivation,
            "fatigue": self.emotion_sensitivity_fatigue,
        }

    @property
    def critic_weights(self) -> CriticWeights:
        """Critic 重み設定を CriticWeights として返す。"""
        return CriticWeights(
            rule_based=self.critic_weight_rule_based,
            statistical=self.critic_weight_statistical,
            llm_judge=self.critic_weight_llm_judge,
        )

    @property
    def state_transition(self) -> StateTransitionConfig:
        """状態遷移設定を StateTransitionConfig として返す。"""
        return StateTransitionConfig(
            decay_rate=self.state_transition_decay_rate,
            event_weight=self.state_transition_event_weight,
            llm_weight=self.state_transition_llm_weight,
            noise_scale=self.state_transition_noise_scale,
        )

    @property
    def temperature_schedule(self) -> list[float]:
        """リトライ時の Temperature スケジュールを生成する。

        初回の Temperature から decay_step ずつ減衰させた
        max_retries 分のリストを返す。

        Returns:
            Temperature のリスト。例: [0.7, 0.5, 0.3]
        """
        return [
            round(self.initial_temperature - (self.temperature_decay_step * i), 10) for i in range(self.max_retries)
        ]
