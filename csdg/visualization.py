"""可視化モジュール -- 感情パラメータ推移と CriticScore 推移グラフを生成する。

architecture.md §7.3 に準拠し、2段構成の state_trajectory.png を出力する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")  # GUI なし環境対応

import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from csdg.schemas import PipelineLog

logger = logging.getLogger(__name__)

# 日本語フォント対応: 利用可能なフォントにフォールバック
_JP_FONTS = ["IPAexGothic", "Hiragino Sans", "Noto Sans CJK JP", "sans-serif"]

_EVENT_MARKER_COLORS: dict[str, str] = {
    "positive": "#2ca02c",
    "negative": "#d62728",
    "neutral": "#7f7f7f",
}


def generate_state_trajectory(
    log: PipelineLog,
    output_path: str = "output/state_trajectory.png",
) -> None:
    """7日間の感情パラメータ推移と CriticScore の推移グラフを生成する。

    2段構成 (figsize=(12, 8)):
    - 上段: stress (赤), motivation (青), fatigue (灰) の折れ線グラフ
    - 下段: temporal_consistency, emotional_plausibility, persona_deviation の折れ線

    Args:
        log: パイプライン実行ログ。
        output_path: 出力ファイルパス。
    """
    # フォント設定
    for font in _JP_FONTS:
        if font != "sans-serif":
            try:
                matplotlib.font_manager.findfont(font, fallback_to_default=False)
                matplotlib.rcParams["font.family"] = font
                break
            except ValueError:
                continue

    records = sorted(log.records, key=lambda r: r.day)
    days = [r.day for r in records]

    if not records:
        logger.warning("[CSDG] レコードが空のため、グラフを生成しません")
        return

    # 感情パラメータ
    stress_vals = [r.final_state.stress for r in records]
    motivation_vals = [r.final_state.motivation for r in records]
    fatigue_vals = [r.final_state.fatigue for r in records]

    # CriticScore (最後の attempt)
    temporal_vals = [r.critic_scores[-1].temporal_consistency for r in records]
    emotional_vals = [r.critic_scores[-1].emotional_plausibility for r in records]
    persona_vals = [r.critic_scores[-1].persona_deviation for r in records]

    # イベントタイプのマーカー色
    marker_colors = [_EVENT_MARKER_COLORS.get(r.event.event_type, "#7f7f7f") for r in records]

    fig, (ax_state, ax_score) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # --- 上段: 感情パラメータ推移 ---
    ax_state.plot(days, stress_vals, "o-", color="#d62728", label="stress", linewidth=2)
    ax_state.plot(days, motivation_vals, "s-", color="#1f77b4", label="motivation", linewidth=2)
    ax_state.plot(days, fatigue_vals, "^-", color="#7f7f7f", label="fatigue", linewidth=2)

    # イベントタイプマーカー
    for d, c in zip(days, marker_colors, strict=True):
        ax_state.axvline(x=d, color=c, alpha=0.15, linewidth=8)

    ax_state.set_ylabel("Parameter Value (-1.0 ~ 1.0)")
    ax_state.set_ylim(-1.1, 1.1)
    ax_state.axhline(y=0, color="black", linewidth=0.5, linestyle="--", alpha=0.3)
    ax_state.legend(loc="upper right")
    ax_state.set_title("Emotional Parameter Trajectory")
    ax_state.grid(True, alpha=0.3)

    # --- 下段: CriticScore 推移 ---
    ax_score.plot(days, temporal_vals, "o-", label="temporal_consistency", linewidth=2)
    ax_score.plot(days, emotional_vals, "s-", label="emotional_plausibility", linewidth=2)
    ax_score.plot(days, persona_vals, "^-", label="persona_deviation", linewidth=2)

    # 合格ライン (スコア 3)
    ax_score.axhline(y=3, color="red", linewidth=1.5, linestyle="--", alpha=0.7, label="Pass line (3)")

    ax_score.set_xlabel("Day")
    ax_score.set_ylabel("CriticScore (1 ~ 5)")
    ax_score.set_ylim(0.5, 5.5)
    ax_score.set_xticks(days)
    ax_score.legend(loc="upper right")
    ax_score.set_title("CriticScore Trajectory")
    ax_score.grid(True, alpha=0.3)

    fig.tight_layout()

    # 保存
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info("[CSDG] Graph saved: %s", out)
