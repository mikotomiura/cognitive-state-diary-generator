"""
状態遷移の半数式化モジュール.

決定論的な骨格 (decay + event_impact) に LLM が提案する delta 補正を加え、
再現性と表現力のバランスを取った状態遷移を実現する。

"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from csdg.schemas import CharacterState, DailyEvent, EmotionalDelta, HumanCondition

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

    continuous_updates: dict[str, float] = {}
    for param in _CONTINUOUS_PARAMS:
        prev_val: float = getattr(prev_state, param)
        impact_val: float = getattr(impact, param)
        delta_val: float = getattr(llm_delta, param)

        # 決定論的骨格: decay + event_impact
        base = prev_val * (1.0 - config.decay_rate) + impact_val * config.event_weight

        # LLM delta を max_llm_delta でクリップ (安定性保証)
        clipped_delta = _clamp(delta_val, -config.max_llm_delta, config.max_llm_delta)

        # LLM 補正 + ノイズ
        noise = rng.gauss(0.0, config.noise_scale) if config.noise_scale > 0 else 0.0
        result = base + clipped_delta * config.llm_weight + noise

        clamp_lo = 0.0 if param == "fatigue" else config.clamp_min
        continuous_updates[param] = _clamp(result, clamp_lo, config.clamp_max)

    # HumanCondition の更新
    new_hc = compute_human_condition(prev_state, event, rng)

    # physical_energy が低い場合、motivation に負の補正
    if new_hc.physical_energy < 0.4:
        energy_penalty = (0.4 - new_hc.physical_energy) * 0.3
        current_motivation = continuous_updates.get("motivation", prev_state.motivation)
        continuous_updates["motivation"] = _clamp(
            current_motivation - energy_penalty,
            config.clamp_min,
            config.clamp_max,
        )

    updates: dict[str, object] = {**continuous_updates, "human_condition": new_hc}
    return prev_state.model_copy(update=updates)


def compute_human_condition(
    prev_state: CharacterState,
    event: DailyEvent,
    rng: random.Random,
) -> HumanCondition:
    """前日の状態とイベントから HumanCondition を算出する.

    決定論的な導出 + 微小なランダムドリフトで人間的な揺らぎを表現する。

    Args:
        prev_state: 前日のキャラクター内部状態.
        event: 当日のイベント定義.
        rng: 乱数生成器.

    Returns:
        更新された HumanCondition.
    """
    prev_hc = prev_state.human_condition

    # --- sleep_quality: 前日の fatigue/stress が高いと翌日の睡眠が悪化 ---
    sleep_base = 0.7  # デフォルトベースライン
    fatigue_penalty = max(0.0, prev_state.fatigue - 0.5) * 0.6
    stress_penalty = max(0.0, prev_state.stress - 0.3) * 0.4
    sleep_quality = _clamp(sleep_base - fatigue_penalty - stress_penalty + rng.gauss(0.0, 0.05), 0.0, 1.0)

    # --- physical_energy: sleep_quality と前日 fatigue から導出 ---
    physical_energy = _clamp(
        sleep_quality * 0.6 + (1.0 - prev_state.fatigue) * 0.4 + rng.gauss(0.0, 0.03),
        0.0,
        1.0,
    )

    # --- mood_baseline: 前日値からランダムドリフト + イベントの微小影響 ---
    mood_drift = rng.gauss(0.0, 0.08)
    event_mood_pull = event.emotional_impact * 0.1
    mood_baseline = _clamp(prev_hc.mood_baseline * 0.85 + mood_drift + event_mood_pull, -1.0, 1.0)

    # --- cognitive_load: unresolved_issue + stress + 前日の認知負荷の減衰 ---
    base_load = prev_hc.cognitive_load * 0.6  # 翌日には部分的に回復
    issue_load = 0.15 if prev_state.unresolved_issue else 0.0
    stress_load = max(0.0, prev_state.stress) * 0.2
    negative_event_load = max(0.0, -event.emotional_impact) * 0.15
    cognitive_load = _clamp(base_load + issue_load + stress_load + negative_event_load, 0.0, 1.0)

    # --- emotional_conflict: 矛盾する感情シグナルの検出 ---
    emotional_conflict = _detect_emotional_conflict(prev_state, event)

    return HumanCondition(
        sleep_quality=sleep_quality,
        physical_energy=physical_energy,
        mood_baseline=mood_baseline,
        cognitive_load=cognitive_load,
        emotional_conflict=emotional_conflict,
    )


def _detect_emotional_conflict(
    prev_state: CharacterState,
    event: DailyEvent,
) -> str | None:
    """矛盾する感情シグナルを検出し、葛藤を文字列で返す.

    Args:
        prev_state: 前日のキャラクター内部状態.
        event: 当日のイベント定義.

    Returns:
        葛藤の記述文字列、または None.
    """
    conflicts: list[str] = []

    # ポジティブイベント + 高ストレス → 喜びと疲弊の葛藤
    if event.emotional_impact > 0.2 and prev_state.stress > 0.3:
        conflicts.append("良い出来事への喜びと、蓄積されたストレスによる疲弊感の同居")

    # ポジティブイベント + 高疲労 → 達成感と身体的限界の葛藤
    if event.emotional_impact > 0.2 and prev_state.fatigue > 0.6:
        conflicts.append("達成感と身体的な消耗の同居")

    # ネガティブイベント + 高モチベーション → 挫折と意欲の葛藤
    if event.emotional_impact < -0.3 and prev_state.motivation > 0.3:
        conflicts.append("挫折感と、それでも前に進みたいという意欲の葛藤")

    # 未解決課題 + ポジティブイベント → 前進と未解決の葛藤
    if prev_state.unresolved_issue and event.emotional_impact > 0.2:
        conflicts.append("新たな前向きな経験と、未解決の問題が心に残る緊張感")

    if not conflicts:
        return None

    return conflicts[0]
