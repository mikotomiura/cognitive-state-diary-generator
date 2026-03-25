"""Critic ログ蓄積モジュール.

Critic 評価結果をログとして蓄積し、過去の失敗パターンを
Actor プロンプトにフィードバックする軽量学習機構を提供する.

advice.md タスク4 に準拠する.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — used at runtime in method bodies

from pydantic import BaseModel, Field

from csdg.schemas import CriticResult  # noqa: TC001 — Pydantic field type requires runtime access

logger = logging.getLogger(__name__)


class CriticLogEntry(BaseModel):
    """1Day 分の Critic 評価ログエントリ.

    各 Day の評価結果、Actor 入力要約、検出された問題パターンを記録する.
    """

    day: int = Field(description="経過日数")
    scores: CriticResult = Field(description="3層 Critic 評価結果")
    actor_input_summary: str = Field(description="Actor 入力の要約 (状態 + イベント)")
    generated_text_hash: str = Field(description="生成テキストの SHA-256 ハッシュ (重複検出用)")
    failure_patterns: list[str] = Field(default_factory=list, description="Layer1/2 で検出された具体的な問題")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class CriticLog:
    """Critic ログの管理を担当する.

    JSON Lines 形式でログを永続化し、過去の低スコアパターンを集計する.

    Attributes:
        _entries: ログエントリのリスト.
    """

    def __init__(self, entries: list[CriticLogEntry] | None = None) -> None:
        self._entries: list[CriticLogEntry] = entries or []

    @property
    def entries(self) -> list[CriticLogEntry]:
        """ログエントリのリスト."""
        return list(self._entries)

    def add(self, entry: CriticLogEntry) -> None:
        """エントリを追加する.

        Args:
            entry: 追加する Critic ログエントリ.
        """
        self._entries.append(entry)
        logger.debug("[CriticLog] Day %d entry added (%d patterns)", entry.day, len(entry.failure_patterns))

    def save(self, path: Path) -> None:
        """JSON Lines 形式で追記保存する.

        Args:
            path: 保存先ファイルパス (.jsonl).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(entry.model_dump_json() + "\n")
        logger.info("[CriticLog] Saved %d entries to %s", len(self._entries), path)

    @classmethod
    def load(cls, path: Path) -> CriticLog:
        """既存ログを読み込む.

        Args:
            path: JSON Lines ファイルパス.

        Returns:
            読み込んだ CriticLog インスタンス.
        """
        entries: list[CriticLogEntry] = []
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        entries.append(CriticLogEntry.model_validate_json(stripped))
                    except Exception:
                        logger.warning("[CriticLog] Failed to parse line %d in %s", line_num, path)
        logger.info("[CriticLog] Loaded %d entries from %s", len(entries), path)
        return cls(entries=entries)

    def get_low_score_patterns(
        self,
        axis: str,
        threshold: float = 3.0,
        top_k: int = 5,
    ) -> list[str]:
        """指定軸で threshold 以下のエントリから failure_patterns を頻度順に返す.

        Args:
            axis: 評価軸名 (temporal_consistency / emotional_plausibility / persona_deviation).
            threshold: この値以下のスコアを低スコアとみなす.
            top_k: 返すパターン数の上限.

        Returns:
            failure_patterns を頻度順にソートしたリスト.
        """
        counter: Counter[str] = Counter()
        for entry in self._entries:
            score_val = getattr(entry.scores.final_score, axis, None)
            if score_val is not None and score_val <= threshold:
                for pattern in entry.failure_patterns:
                    counter[pattern] += 1

        return [pattern for pattern, _ in counter.most_common(top_k)]

    def get_all_low_score_patterns(
        self,
        threshold: float = 3.0,
        top_k: int = 5,
    ) -> list[str]:
        """全軸を横断して低スコアパターンを頻度順に返す.

        Args:
            threshold: この値以下のスコアを低スコアとみなす.
            top_k: 返すパターン数の上限.

        Returns:
            failure_patterns を頻度順にソートしたリスト.
        """
        axes = ("temporal_consistency", "emotional_plausibility", "persona_deviation")
        counter: Counter[str] = Counter()
        for entry in self._entries:
            is_low = any(getattr(entry.scores.final_score, ax) <= threshold for ax in axes)
            if is_low:
                for pattern in entry.failure_patterns:
                    counter[pattern] += 1

        return [pattern for pattern, _ in counter.most_common(top_k)]


def compute_text_hash(text: str) -> str:
    """テキストの SHA-256 ハッシュを算出する.

    Args:
        text: ハッシュ対象テキスト.

    Returns:
        16進数文字列の SHA-256 ハッシュ.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_failure_patterns(critic_result: CriticResult) -> list[str]:
    """CriticResult の Layer1/2 details から failure_patterns を抽出する.

    Args:
        critic_result: 3層 Critic 評価結果.

    Returns:
        検出された問題パターンの文字列リスト.
    """
    patterns: list[str] = []

    # Layer 1: RuleBased の details から問題を抽出
    l1 = critic_result.rule_based.details
    if l1.get("char_count_violation") == "too_short":
        patterns.append("文字数が下限を下回っている")
    if l1.get("char_count_violation") == "too_long":
        patterns.append("文字数が上限を超えている")
    if l1.get("emoji_count"):
        patterns.append("禁止表現(絵文字)が含まれている")
    if l1.get("overlap_violation"):
        patterns.append("前日との表現が類似しすぎる(特に冒頭の書き出し)")
    for param in ("fatigue", "motivation", "stress"):
        if l1.get(f"{param}_direction_mismatch"):
            patterns.append(f"感情変化({param})がイベントの方向と矛盾している")

    # Layer 2: Statistical の details から問題を抽出
    l2 = critic_result.statistical.details
    max_dev = l2.get("max_deviation")
    if isinstance(max_dev, (int, float)) and max_dev > 0.5:
        patterns.append("感情変化がイベントの重大さに対して不適切")
    if l2.get("excessive_assertions"):
        patterns.append("断定文が多すぎる(ペルソナの禁則事項に抵触)")

    return patterns


def build_feedback_prompt(patterns: list[str]) -> str:
    """過去の失敗パターンから Actor プロンプト注入用テキストを構築する.

    Args:
        patterns: 過去の failure_patterns リスト.

    Returns:
        Actor プロンプトに注入する警告テキスト. パターンが空の場合は空文字列.
    """
    if not patterns:
        return ""

    lines = ["## 過去の品質問題(これらを避けてください)"]
    for p in patterns:
        lines.append(f"- {p}")
    return "\n".join(lines)
