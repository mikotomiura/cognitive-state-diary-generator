"""CSDG 品質サマリレポート生成スクリプト。

generation_log.json を解析し、日記品質の各種メトリクスを集計・判定する。
全品質基準を満たす場合は exit code 0、違反がある場合は exit code 1 で終了する。

Usage:
    python scripts/quality_report.py path/to/generation_log.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from csdg.engine.constants import SCENE_MARKER_HARD_DAYS, THEME_WORD_HARD_LIMIT
from csdg.engine.pipeline import (
    _count_theme_words,
    _detect_ending_pattern,
    _detect_opening_pattern,
    _detect_scene_markers,
    _detect_structure_pattern,
    _extract_used_philosophers,
)

# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def _load_log(path: Path) -> dict[str, Any]:
    """generation_log.json を読み込んで辞書として返す。"""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _get_records(log_data: dict[str, Any]) -> list[dict[str, Any]]:
    """PipelineLog からレコード一覧を取得する。"""
    return log_data.get("records", [])  # type: ignore[no-any-return]


def _get_executed_at(log_data: dict[str, Any]) -> str:
    """実行日時文字列を返す。metadata が無ければ現在時刻。"""
    if "executed_at" in log_data:
        return str(log_data["executed_at"])
    metadata = log_data.get("metadata", {})
    if "started_at" in metadata:
        return str(metadata["started_at"])
    return datetime.now().isoformat()


def _get_score(record: dict[str, Any]) -> dict[str, int]:
    """レコードからスコア辞書を取得する。

    critic_scores リストの最後 (最終評価) を使用する。
    """
    critic_scores = record.get("critic_scores", [])
    if critic_scores:
        last = critic_scores[-1]
        if isinstance(last, dict):
            return {
                "temporal_consistency": last.get("temporal_consistency", 0),
                "emotional_plausibility": last.get("emotional_plausibility", 0),
                "persona_deviation": last.get("persona_deviation", 0),
            }
    # フォールバック: score フィールドが直接ある場合
    score = record.get("score", {})
    if isinstance(score, dict):
        return {
            "temporal_consistency": score.get("temporal_consistency", 0),
            "emotional_plausibility": score.get("emotional_plausibility", 0),
            "persona_deviation": score.get("persona_deviation", 0),
        }
    return {"temporal_consistency": 0, "emotional_plausibility": 0, "persona_deviation": 0}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(log_data: dict[str, Any]) -> bool:
    """品質サマリレポートを stdout に出力し、全基準 PASS なら True を返す。"""
    records = _get_records(log_data)
    num_days = len(records)
    total_retries = sum(r.get("retry_count", 0) for r in records)
    total_fallbacks = sum(1 for r in records if r.get("fallback_used", r.get("is_fallback", False)))

    executed_at = _get_executed_at(log_data)

    # --- 各 Day の解析 ---
    temporal_scores: list[int] = []
    emotional_scores: list[int] = []
    persona_scores: list[int] = []
    opening_patterns: list[tuple[int, str]] = []
    ending_patterns: list[tuple[int, str]] = []
    structure_patterns: list[tuple[int, str]] = []
    theme_word_totals: Counter[str] = Counter()
    scene_marker_days: dict[str, set[int]] = {}
    philosopher_counts: Counter[str] = Counter()
    char_counts: list[tuple[int, int]] = []

    for record in records:
        day = record.get("day", 0)
        diary_text = record.get("diary_text", "")
        score = _get_score(record)

        temporal_scores.append(score["temporal_consistency"])
        emotional_scores.append(score["emotional_plausibility"])
        persona_scores.append(score["persona_deviation"])

        opening_patterns.append((day, _detect_opening_pattern(diary_text)))
        ending_patterns.append((day, _detect_ending_pattern(diary_text)))
        structure_patterns.append((day, _detect_structure_pattern(diary_text)))

        word_counts = _count_theme_words(diary_text)
        for word, count in word_counts.items():
            theme_word_totals[word] += count

        markers = _detect_scene_markers(diary_text)
        for marker in markers:
            scene_marker_days.setdefault(marker, set()).add(day)

        philosophers = _extract_used_philosophers(diary_text)
        philosopher_counts.update(philosophers)

        char_counts.append((day, len(diary_text)))

    total_scores = [t + e + p for t, e, p in zip(temporal_scores, emotional_scores, persona_scores, strict=True)]

    # --- ヘッダー ---
    print("=== CSDG 品質サマリレポート ===")
    print(f"実行日時: {executed_at}")
    print(f"総Day数: {num_days} / リトライ: {total_retries} / フォールバック: {total_fallbacks}")
    print()

    # --- Critic スコアサマリ ---
    print("--- Critic スコアサマリ ---")
    _print_score_line("temporal", temporal_scores)
    _print_score_line("emotional", emotional_scores)
    _print_score_line("persona", persona_scores)
    if total_scores:
        avg_total = sum(total_scores) / len(total_scores)
        print(f"  合計:        {total_scores}  avg={avg_total:.2f}")
    print()

    # --- 書き出しパターン分布 ---
    print("--- 書き出しパターン分布 ---")
    opening_counter = Counter(pat for _, pat in opening_patterns)
    for pat, count in opening_counter.most_common():
        days_str = ", ".join(str(d) for d, p in opening_patterns if p == pat)
        print(f"  {pat}: {count}回 (Day {days_str})")
    unique_openings = len(opening_counter)
    opening_ok = unique_openings >= 5
    mark = "\u2705" if opening_ok else "\u26a0\ufe0f"
    print(f"  ユニーク数: {unique_openings}/{num_days}  {mark}")
    print()

    # --- 余韻パターン分布 ---
    print("--- 余韻パターン分布 ---")
    ending_counter = Counter(pat for _, pat in ending_patterns)
    for pat, count in ending_counter.most_common():
        days_str = ", ".join(str(d) for d, p in ending_patterns if p == pat)
        print(f"  {pat}: {count}回 (Day {days_str})")
    unique_endings = len(ending_counter)
    ending_ok = unique_endings >= 5
    mark = "\u2705" if ending_ok else "\u26a0\ufe0f"
    print(f"  ユニーク数: {unique_endings}/{num_days}  {mark}")
    other_ending_count = ending_counter.get("その他", 0)
    other_ending_ok = other_ending_count <= 1
    mark = "\u2705" if other_ending_ok else "\u26a0\ufe0f"
    print(f"  「その他」回数: {other_ending_count}  {mark}")
    print()

    # --- 場面構造パターン分布 ---
    print("--- 場面構造パターン分布 ---")
    structure_counter = Counter(pat for _, pat in structure_patterns)
    pattern_limits: dict[str, int] = {"古書店型": 2, "帰路型": 2}
    has_consecutive_structure = False
    for i in range(1, len(structure_patterns)):
        if structure_patterns[i][1] == structure_patterns[i - 1][1] and structure_patterns[i][1] != "その他":
            has_consecutive_structure = True
            break

    for pat, count in structure_counter.most_common():
        days_str = ", ".join(str(d) for d, p in structure_patterns if p == pat)
        limit = pattern_limits.get(pat)
        if limit is not None:
            status = "OK" if count <= limit else "NG"
            print(f"  {pat}: {count}回 (Day {days_str})  [上限{limit}: {status}]")
        else:
            print(f"  {pat}: {count}回 (Day {days_str})")

    consecutive_mark = "\u2705" if not has_consecutive_structure else "\u26a0\ufe0f"
    consecutive_label = "なし" if not has_consecutive_structure else "あり"
    print(f"  連続同一構造: {consecutive_label}  {consecutive_mark}")
    print()

    # --- 主題語の累計使用回数 ---
    print("--- 主題語の累計使用回数 ---")
    total_theme_count = 0
    for word, count in theme_word_totals.most_common():
        if count == 0:
            continue
        status = "OK" if count <= THEME_WORD_HARD_LIMIT else "NG"
        print(f"  「{word}」: {count}回  [ハードリミット{THEME_WORD_HARD_LIMIT}: {status}]")
        total_theme_count += count
    print(f"  主題語合計: {total_theme_count}回")
    print()

    # --- シーンマーカー出現日数 ---
    print("--- シーンマーカー出現日数 ---")
    for marker, days_set in sorted(scene_marker_days.items(), key=lambda x: -len(x[1])):
        day_count = len(days_set)
        warn = "  \u26a0\ufe0f" if day_count >= SCENE_MARKER_HARD_DAYS else ""
        print(f"  {marker}: {day_count}日{warn}")
    if not scene_marker_days:
        print("  (なし)")
    print()

    # --- 哲学者・思想家の使用回数 ---
    print("--- 哲学者・思想家の使用回数 ---")
    for name, count in philosopher_counts.most_common():
        print(f"  {name}: {count}回")
    unique_philosophers = len(philosopher_counts)
    print(f"  ユニーク人数: {unique_philosophers}")
    print()

    # --- 文字数統計 ---
    print("--- 文字数統計 ---")
    for day, cc in char_counts:
        print(f"  Day {day}: {cc:,}文字")
    if char_counts:
        counts_only = [cc for _, cc in char_counts]
        avg_chars = sum(counts_only) / len(counts_only)
        min_chars = min(counts_only)
        max_chars = max(counts_only)
        print(f"  平均: {avg_chars:,.0f}文字  範囲: [{min_chars:,}, {max_chars:,}]")
    print()

    # --- 判定 ---
    print("=== 判定 ===")
    failures: list[str] = []

    # 書き出し多様性
    _judge(
        f"書き出し多様性: {unique_openings}種/{num_days}日 (目標>=5)",
        opening_ok,
        failures,
    )

    # 余韻多様性
    _judge(
        f"余韻多様性: {unique_endings}種/{num_days}日 (目標>=5)",
        ending_ok,
        failures,
    )

    # 「その他」余韻
    _judge(
        f"「その他」余韻: {other_ending_count}回 (目標<=1)",
        other_ending_ok,
        failures,
    )

    # 構造多様性
    consecutive_ok = not has_consecutive_structure
    _judge(
        f"構造多様性: 連続{consecutive_label} (目標: 連続なし)",
        consecutive_ok,
        failures,
    )

    # 古書店型上限
    koshotencount = structure_counter.get("古書店型", 0)
    _judge(
        f"古書店型上限: {koshotencount}回 (上限2)",
        koshotencount <= 2,
        failures,
    )

    # 帰路型上限
    kirocount = structure_counter.get("帰路型", 0)
    _judge(
        f"帰路型上限: {kirocount}回 (上限2)",
        kirocount <= 2,
        failures,
    )

    # Critic 全 Day Pass (各 Day の合計スコア >= 9)
    pass_days = sum(1 for t in total_scores if t >= 9)
    _judge(
        f"Critic 全Day Pass: {pass_days}/{num_days}",
        pass_days == num_days,
        failures,
    )

    # フォールバック率
    _judge(
        f"フォールバック率: {total_fallbacks}/{num_days} (目標<=1)",
        total_fallbacks <= 1,
        failures,
    )

    print()
    if not failures:
        print("結果: 全ての品質基準を満たしています。")
        return True
    else:
        print(f"結果: {len(failures)}件の品質基準に違反しています。")
        return False


def _print_score_line(label: str, scores: list[int]) -> None:
    """スコア行を整形して出力する。"""
    if not scores:
        print(f"  {label + ':':13s} (データなし)")
        return
    avg = sum(scores) / len(scores)
    score_range = max(scores) - min(scores)
    print(f"  {label + ':':13s} {scores}  avg={avg:.2f}  range={score_range}")


def _judge(description: str, passed: bool, failures: list[str]) -> None:
    """判定結果を出力し、FAIL の場合は failures に追加する。"""
    status = "PASS" if passed else "FAIL"
    mark = "\u2705" if passed else "\u274c"
    print(f"  {description}  [{status}] {mark}")
    if not passed:
        failures.append(description)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI エントリポイント。"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/quality_report.py <generation_log.json>", file=sys.stderr)
        sys.exit(2)

    log_path = Path(sys.argv[1])
    if not log_path.exists():
        print(f"Error: ファイルが見つかりません: {log_path}", file=sys.stderr)
        sys.exit(2)

    log_data = _load_log(log_path)
    all_passed = generate_report(log_data)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
