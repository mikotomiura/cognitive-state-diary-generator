"""状態遷移の半数式化モジュール.

決定論的な骨格 (decay + event_impact) に LLM が提案する delta 補正を加え、
再現性と表現力のバランスを取った状態遷移を実現する。

advice.md タスク2 に準拠する。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from csdg.schemas import CharacterState, DailyEvent, EmotionalDelta

if TYPE_CHECKING:
    from csdg.config import StateTransitionConfig

_CONTINUOUS_PARAMS = ("fatigue", "motivation", "stress")


def _clamp(value: float, lo: float, hi: float) -> float:
    """値を [lo, hi] にクランプする。"""
    return max(lo, min(hi, value))


def compute_event_impact(
    event: DailyEvent,
    sensitivity: dict[str, float],
) -> EmotionalDelta:
    """イベントの emotional_impact と感情感度係数から EventImpact を算出する.

    Args:
        event: 当日のイベント.
        sensitivity: 感情感度係数 (e.g. {"stress": -0.3, ...}).

    Returns:
        各パラメータの期待変動幅を EmotionalDelta として返す.
    """
    return EmotionalDelta(
        fatigue=event.emotional_impact * sensitivity.get("fatigue", 0.0),
        motivation=event.emotional_impact * sensitivity.get("motivation", 0.0),
        stress=event.emotional_impact * sensitivity.get("stress", 0.0),
    )


def compute_next_state(
    prev_state: CharacterState,
    event: DailyEvent,
    llm_delta: EmotionalDelta,
    config: StateTransitionConfig,
    sensitivity: dict[str, float],
    *,
    seed: int | None = None,
) -> CharacterState:
    """決定論的骨格 + LLM delta 補正 + 微小ノイズで次の状態を算出する.

    Formula::

        event_impact = emotional_impact * sensitivity[param]
        base = prev * (1 - decay) + event_impact * event_weight
        h_t[param] = base + llm_delta[param] * llm_weight + noise
        clamp(h_t[param], clamp_min, clamp_max)

    Args:
        prev_state: 前日のキャラクター内部状態 (h_{t-1}).
        event: 当日のイベント定義.
        llm_delta: LLM が提案する感情パラメータの補正値.
        config: 状態遷移設定.
        sensitivity: 感情感度係数.
        seed: 乱数シード. None の場合はランダム.

    Returns:
        更新された CharacterState (連続変数のみ更新, 離散変数は prev_state を引き継ぐ).
    """
    rng = random.Random(seed)
    impact = compute_event_impact(event, sensitivity)

    updates: dict[str, float] = {}
    for param in _CONTINUOUS_PARAMS:
        prev_val = getattr(prev_state, param)
        impact_val = getattr(impact, param)
        delta_val = getattr(llm_delta, param)

        # 決定論的骨格: decay + event_impact
        base = prev_val * (1.0 - config.decay_rate) + impact_val * config.event_weight

        # LLM delta を max_llm_delta でクリップ (安定性保証)
        clipped_delta = _clamp(delta_val, -config.max_llm_delta, config.max_llm_delta)

        # LLM 補正 + ノイズ
        noise = rng.gauss(0.0, config.noise_scale) if config.noise_scale > 0 else 0.0
        result = base + clipped_delta * config.llm_weight + noise

        updates[param] = _clamp(result, config.clamp_min, config.clamp_max)

    return prev_state.model_copy(update=updates)
