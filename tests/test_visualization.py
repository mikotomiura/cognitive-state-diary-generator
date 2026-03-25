"""csdg/visualization.py のテスト。

PipelineLog のサンプルデータからグラフ生成が正常完了すること、
出力ファイルの存在、リソースリーク防止 (plt.close) を検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import pytest

from csdg.schemas import (
    CharacterState,
    CriticScore,
    DailyEvent,
    GenerationRecord,
    PipelineLog,
)
from csdg.visualization import generate_state_trajectory


def _make_record(day: int) -> GenerationRecord:
    """テスト用の GenerationRecord を生成する。"""
    event = DailyEvent(
        day=day,
        event_type=["neutral", "positive", "negative"][day % 3],
        domain="仕事",
        description="テスト用イベントの説明テキストです。",
        emotional_impact=0.2 * (day - 4),
    )
    state = CharacterState(
        fatigue=0.1 * day,
        motivation=0.5 - 0.05 * day,
        stress=-0.1 + 0.1 * day,
        current_focus="テスト",
        growth_theme="テーマ",
        memory_buffer=[],
        relationships={},
    )
    score = CriticScore(
        temporal_consistency=3 + (day % 3),
        emotional_plausibility=3 + ((day + 1) % 3),
        persona_deviation=4,
    )
    return GenerationRecord(
        day=day,
        event=event,
        initial_state=state,
        final_state=state,
        diary_text=f"Day {day} の日記テキスト",
        critic_scores=[score],
        retry_count=0,
        fallback_used=False,
        temperature_used=0.7,
        phase1_duration_ms=100,
        phase2_duration_ms=200,
        phase3_duration_ms=150,
        expected_delta={"stress": 0.01, "motivation": -0.02, "fatigue": 0.01},
        actual_delta={"stress": 0.02, "motivation": -0.01, "fatigue": 0.01},
        deviation={"stress": 0.01, "motivation": 0.01, "fatigue": 0.0},
    )


@pytest.fixture()
def sample_log() -> PipelineLog:
    """7Day 分のサンプル PipelineLog を生成する。"""
    return PipelineLog(
        executed_at=datetime.now(tz=UTC),
        config_summary={"model": "gpt-4o"},
        prompt_hashes={},
        records=[_make_record(d) for d in range(1, 8)],
        total_duration_ms=10000,
        total_api_calls=21,
        total_retries=0,
        total_fallbacks=0,
    )


class TestGenerateStateTrajectory:
    """generate_state_trajectory のテスト。"""

    def test_generates_png_file(self, sample_log: PipelineLog, tmp_path: Path) -> None:
        """グラフ PNG ファイルが生成されること。"""
        output = str(tmp_path / "trajectory.png")
        generate_state_trajectory(sample_log, output_path=output)

        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_plt_close_called(self, sample_log: PipelineLog, tmp_path: Path) -> None:
        """plt.close() が呼ばれていること (リソースリーク防止)。"""
        output = str(tmp_path / "trajectory.png")
        with patch.object(plt, "close", wraps=plt.close) as mock_close:
            generate_state_trajectory(sample_log, output_path=output)
            mock_close.assert_called_once()

    def test_empty_records_skips_generation(self, tmp_path: Path) -> None:
        """レコードが空の場合、ファイルを生成しないこと。"""
        empty_log = PipelineLog(
            executed_at=datetime.now(tz=UTC),
            config_summary={},
            prompt_hashes={},
            records=[],
            total_duration_ms=0,
            total_api_calls=0,
            total_retries=0,
            total_fallbacks=0,
        )
        output = str(tmp_path / "no_output.png")
        generate_state_trajectory(empty_log, output_path=output)

        assert not Path(output).exists()

    def test_creates_output_directory(self, sample_log: PipelineLog, tmp_path: Path) -> None:
        """出力ディレクトリが存在しない場合、自動作成されること。"""
        output = str(tmp_path / "subdir" / "deep" / "trajectory.png")
        generate_state_trajectory(sample_log, output_path=output)

        assert Path(output).exists()
