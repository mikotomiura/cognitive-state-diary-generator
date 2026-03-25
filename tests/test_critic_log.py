"""csdg/engine/critic_log.py のテスト.

CriticLogEntry の保存/読み込み、パターン集計、フィードバック構築を検証する.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from csdg.engine.critic_log import (
    CriticLog,
    CriticLogEntry,
    build_feedback_prompt,
    compute_text_hash,
    extract_failure_patterns,
)
from csdg.schemas import CriticResult, CriticScore, LayerScore


# ====================================================================
# フィクスチャ
# ====================================================================


def _make_layer_score(
    temporal: float = 5.0,
    emotional: float = 5.0,
    persona: float = 5.0,
    details: dict[str, object] | None = None,
) -> LayerScore:
    return LayerScore(
        temporal_consistency=temporal,
        emotional_plausibility=emotional,
        persona_deviation=persona,
        details=details or {},
    )


def _make_critic_result(
    temporal: int = 4,
    emotional: int = 4,
    persona: int = 4,
    l1_details: dict[str, object] | None = None,
    l2_details: dict[str, object] | None = None,
) -> CriticResult:
    return CriticResult(
        rule_based=_make_layer_score(details=l1_details or {}),
        statistical=_make_layer_score(details=l2_details or {}),
        llm_judge=_make_layer_score(details={"reject_reason": None, "revision_instruction": None}),
        final_score=CriticScore(
            temporal_consistency=temporal,
            emotional_plausibility=emotional,
            persona_deviation=persona,
        ),
    )


def _make_low_score_result(
    temporal: int = 2,
    emotional: int = 2,
    persona: int = 2,
    l1_details: dict[str, object] | None = None,
    l2_details: dict[str, object] | None = None,
) -> CriticResult:
    return CriticResult(
        rule_based=_make_layer_score(details=l1_details or {}),
        statistical=_make_layer_score(details=l2_details or {}),
        llm_judge=_make_layer_score(details={"reject_reason": "問題あり", "revision_instruction": "修正してください"}),
        final_score=CriticScore(
            temporal_consistency=temporal,
            emotional_plausibility=emotional,
            persona_deviation=persona,
            reject_reason="問題あり",
            revision_instruction="修正してください",
        ),
    )


def _make_entry(
    day: int = 1,
    scores: CriticResult | None = None,
    failure_patterns: list[str] | None = None,
) -> CriticLogEntry:
    return CriticLogEntry(
        day=day,
        scores=scores or _make_critic_result(),
        actor_input_summary=f"Day {day} summary",
        generated_text_hash=compute_text_hash(f"diary text day {day}"),
        failure_patterns=failure_patterns or [],
        timestamp=datetime(2026, 3, 25, tzinfo=UTC),
    )


# ====================================================================
# CriticLogEntry のテスト
# ====================================================================


class TestCriticLogEntry:
    """CriticLogEntry の基本テスト."""

    def test_create_entry(self) -> None:
        """エントリが正しく作成できる."""
        entry = _make_entry(day=1, failure_patterns=["問題A"])
        assert entry.day == 1
        assert entry.failure_patterns == ["問題A"]
        assert len(entry.generated_text_hash) == 64  # SHA-256

    def test_default_timestamp(self) -> None:
        """timestamp が自動設定される."""
        entry = CriticLogEntry(
            day=1,
            scores=_make_critic_result(),
            actor_input_summary="summary",
            generated_text_hash="abc",
        )
        assert entry.timestamp is not None


# ====================================================================
# CriticLog の保存/読み込みテスト
# ====================================================================


class TestCriticLogPersistence:
    """JSON Lines 形式の保存/読み込みテスト."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """保存と読み込みが往復で一致する."""
        log = CriticLog()
        log.add(_make_entry(day=1, failure_patterns=["問題A"]))
        log.add(_make_entry(day=2, failure_patterns=["問題B", "問題C"]))

        file_path = tmp_path / "critic_log.jsonl"
        log.save(file_path)

        loaded = CriticLog.load(file_path)
        assert len(loaded.entries) == 2
        assert loaded.entries[0].day == 1
        assert loaded.entries[0].failure_patterns == ["問題A"]
        assert loaded.entries[1].day == 2
        assert loaded.entries[1].failure_patterns == ["問題B", "問題C"]

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """空ファイルでも正常に読み込める."""
        file_path = tmp_path / "empty.jsonl"
        file_path.touch()

        loaded = CriticLog.load(file_path)
        assert len(loaded.entries) == 0

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """存在しないファイルでも空ログを返す."""
        loaded = CriticLog.load(tmp_path / "nonexistent.jsonl")
        assert len(loaded.entries) == 0

    def test_load_corrupted_lines_skipped(self, tmp_path: Path) -> None:
        """不正な行がスキップされる."""
        file_path = tmp_path / "corrupt.jsonl"
        log = CriticLog()
        log.add(_make_entry(day=1))
        log.save(file_path)

        # 不正行を追加
        with file_path.open("a", encoding="utf-8") as f:
            f.write("this is not valid json\n")

        loaded = CriticLog.load(file_path)
        assert len(loaded.entries) == 1
        assert loaded.entries[0].day == 1


# ====================================================================
# get_low_score_patterns のテスト
# ====================================================================


class TestGetLowScorePatterns:
    """パターン集計のテスト."""

    def test_empty_log_returns_empty(self) -> None:
        """空ログで空リストが返る."""
        log = CriticLog()
        assert log.get_low_score_patterns("emotional_plausibility") == []

    def test_patterns_sorted_by_frequency(self) -> None:
        """頻度順にソートされている."""
        log = CriticLog()
        log.add(_make_entry(
            day=1,
            scores=_make_low_score_result(emotional=2),
            failure_patterns=["問題A", "問題B"],
        ))
        log.add(_make_entry(
            day=2,
            scores=_make_low_score_result(emotional=2),
            failure_patterns=["問題A", "問題C"],
        ))
        log.add(_make_entry(
            day=3,
            scores=_make_low_score_result(emotional=1),
            failure_patterns=["問題A"],
        ))

        patterns = log.get_low_score_patterns("emotional_plausibility")
        assert patterns[0] == "問題A"  # 出現3回
        assert "問題B" in patterns
        assert "問題C" in patterns

    def test_threshold_filtering(self) -> None:
        """threshold 以上のスコアはフィルタされる."""
        log = CriticLog()
        log.add(_make_entry(
            day=1,
            scores=_make_critic_result(temporal=4),
            failure_patterns=["高スコアの問題"],
        ))
        log.add(_make_entry(
            day=2,
            scores=_make_low_score_result(temporal=2),
            failure_patterns=["低スコアの問題"],
        ))

        patterns = log.get_low_score_patterns("temporal_consistency", threshold=3.0)
        assert "低スコアの問題" in patterns
        assert "高スコアの問題" not in patterns

    def test_top_k_limit(self) -> None:
        """top_k で結果数が制限される."""
        log = CriticLog()
        for i in range(10):
            log.add(_make_entry(
                day=i,
                scores=_make_low_score_result(emotional=2),
                failure_patterns=[f"問題{i}"],
            ))

        patterns = log.get_low_score_patterns("emotional_plausibility", top_k=3)
        assert len(patterns) <= 3

    def test_get_all_low_score_patterns(self) -> None:
        """全軸横断でパターンを取得する."""
        log = CriticLog()
        log.add(_make_entry(
            day=1,
            scores=_make_low_score_result(temporal=2, emotional=4, persona=4),
            failure_patterns=["temporal問題"],
        ))
        log.add(_make_entry(
            day=2,
            scores=_make_low_score_result(temporal=4, emotional=2, persona=4),
            failure_patterns=["emotional問題"],
        ))

        patterns = log.get_all_low_score_patterns()
        assert "temporal問題" in patterns
        assert "emotional問題" in patterns


# ====================================================================
# extract_failure_patterns のテスト
# ====================================================================


class TestExtractFailurePatterns:
    """CriticResult からのパターン抽出テスト."""

    def test_no_issues_returns_empty(self) -> None:
        """問題がない場合は空リスト."""
        result = _make_critic_result()
        assert extract_failure_patterns(result) == []

    def test_char_count_too_short(self) -> None:
        """文字数下限違反を検出する."""
        result = _make_critic_result(l1_details={"char_count_violation": "too_short"})
        patterns = extract_failure_patterns(result)
        assert "文字数が下限を下回っている" in patterns

    def test_emoji_detected(self) -> None:
        """絵文字検出を検出する."""
        result = _make_critic_result(l1_details={"emoji_count": 3})
        patterns = extract_failure_patterns(result)
        assert "禁止表現(絵文字)が含まれている" in patterns

    def test_overlap_violation(self) -> None:
        """前日との重複違反を検出する."""
        result = _make_critic_result(l1_details={"overlap_violation": True})
        patterns = extract_failure_patterns(result)
        assert "前日との表現が類似しすぎる(特に冒頭の書き出し)" in patterns

    def test_direction_mismatch(self) -> None:
        """感情方向の不一致を検出する."""
        result = _make_critic_result(l1_details={"stress_direction_mismatch": True})
        patterns = extract_failure_patterns(result)
        assert "感情変化(stress)がイベントの方向と矛盾している" in patterns

    def test_excessive_deviation(self) -> None:
        """感情変化の不適切さを検出する."""
        result = _make_critic_result(l2_details={"max_deviation": 0.8})
        patterns = extract_failure_patterns(result)
        assert "感情変化がイベントの重大さに対して不適切" in patterns

    def test_excessive_assertions(self) -> None:
        """断定文過多を検出する."""
        result = _make_critic_result(l2_details={"excessive_assertions": 5})
        patterns = extract_failure_patterns(result)
        assert "断定文が多すぎる(ペルソナの禁則事項に抵触)" in patterns


# ====================================================================
# build_feedback_prompt のテスト
# ====================================================================


class TestBuildFeedbackPrompt:
    """フィードバックプロンプト構築のテスト."""

    def test_empty_patterns_returns_empty(self) -> None:
        """パターンが空の場合は空文字列."""
        assert build_feedback_prompt([]) == ""

    def test_patterns_included(self) -> None:
        """パターンがプロンプトに含まれる."""
        prompt = build_feedback_prompt(["問題A", "問題B"])
        assert "過去の品質問題" in prompt  # noqa: RUF001
        assert "- 問題A" in prompt
        assert "- 問題B" in prompt


# ====================================================================
# compute_text_hash のテスト
# ====================================================================


class TestComputeTextHash:
    """テキストハッシュのテスト."""

    def test_deterministic(self) -> None:
        """同一テキストで同一ハッシュ."""
        assert compute_text_hash("hello") == compute_text_hash("hello")

    def test_different_text_different_hash(self) -> None:
        """異なるテキストで異なるハッシュ."""
        assert compute_text_hash("hello") != compute_text_hash("world")

    def test_hash_length(self) -> None:
        """SHA-256 は64文字の16進数."""
        assert len(compute_text_hash("test")) == 64
