"""csdg/main.py のテスト.

parse_args, save_diary, run_pipeline の各関数を検証する.
test-standards/SKILL.md の AAA パターンおよび命名規約に従う.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from csdg.main import (
    _EXIT_ABORT,
    _EXIT_CONFIG_ERROR,
    _EXIT_OK,
    _EXIT_PARTIAL,
    parse_args,
    run_pipeline,
    save_diary,
)
from csdg.schemas import (
    CharacterState,
    CriticScore,
    DailyEvent,
    GenerationRecord,
)

# ====================================================================
# フィクスチャ
# ====================================================================


def _make_record(
    day: int = 1,
    diary_text: str = "テスト日記テキストです。" * 10,
    critic_scores: list[CriticScore] | None = None,
    fallback_used: bool = False,
) -> GenerationRecord:
    """テスト用 GenerationRecord を生成する."""
    event = DailyEvent(
        day=day,
        event_type="neutral",
        domain="仕事",
        description="テストイベントの説明文です",
        emotional_impact=0.2,
    )
    state = CharacterState(
        fatigue=0.3,
        motivation=0.4,
        stress=-0.1,
        current_focus="テスト",
        growth_theme="テストテーマ",
    )
    if critic_scores is None:
        critic_scores = [
            CriticScore(
                temporal_consistency=4,
                emotional_plausibility=4,
                persona_deviation=5,
            )
        ]
    return GenerationRecord(
        day=day,
        event=event,
        initial_state=state,
        final_state=state,
        diary_text=diary_text,
        critic_scores=critic_scores,
        retry_count=0,
        fallback_used=fallback_used,
        temperature_used=0.7,
        phase1_duration_ms=100,
        phase2_duration_ms=200,
        phase3_duration_ms=300,
        expected_delta={"stress": -0.06, "motivation": 0.08, "fatigue": -0.04},
        actual_delta={"stress": -0.05, "motivation": 0.07, "fatigue": -0.03},
        deviation={"stress": 0.01, "motivation": -0.01, "fatigue": 0.01},
    )


# ====================================================================
# parse_args のテスト
# ====================================================================


class TestParseArgs:
    """parse_args の検証."""

    def test_default_args(self) -> None:
        """引数なしでデフォルト値が設定される."""
        args = parse_args([])
        assert args.day is None
        assert args.output_dir is None
        assert args.verbose is False
        assert args.skip_visualization is False
        assert args.dry_run is False

    def test_day_option(self) -> None:
        """--day で特定の日を指定できる."""
        args = parse_args(["--day", "3"])
        assert args.day == 3

    def test_output_dir_option(self) -> None:
        """--output-dir で出力先を指定できる."""
        args = parse_args(["--output-dir", "custom_output"])
        assert args.output_dir == "custom_output"

    def test_verbose_flag(self) -> None:
        """--verbose でフラグが True になる."""
        args = parse_args(["--verbose"])
        assert args.verbose is True

    def test_skip_visualization_flag(self) -> None:
        """--skip-visualization でフラグが True になる."""
        args = parse_args(["--skip-visualization"])
        assert args.skip_visualization is True

    def test_dry_run_flag(self) -> None:
        """--dry-run でフラグが True になる."""
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_combined_options(self) -> None:
        """複数オプションを同時に指定できる."""
        args = parse_args(["--day", "5", "--verbose", "--dry-run"])
        assert args.day == 5
        assert args.verbose is True
        assert args.dry_run is True


# ====================================================================
# save_diary のテスト
# ====================================================================


class TestSaveDiary:
    """save_diary の検証."""

    def test_creates_markdown_file(self, tmp_path: Path) -> None:
        """Markdown ファイルが作成される."""
        record = _make_record(day=1)
        path = save_diary(record, str(tmp_path))
        assert path.exists()
        assert path.name == "day_01.md"

    def test_frontmatter_contains_day(self, tmp_path: Path) -> None:
        """フロントマターに day が含まれる."""
        record = _make_record(day=3)
        path = save_diary(record, str(tmp_path))
        content = path.read_text(encoding="utf-8")
        assert "day: 3" in content

    def test_frontmatter_contains_critic_score(self, tmp_path: Path) -> None:
        """フロントマターに CriticScore が含まれる."""
        record = _make_record()
        path = save_diary(record, str(tmp_path))
        content = path.read_text(encoding="utf-8")
        assert "critic_score:" in content
        assert "temporal_consistency: 4" in content

    def test_no_critic_score_when_empty(self, tmp_path: Path) -> None:
        """critic_scores が空の場合、critic_score セクションが含まれない."""
        record = _make_record(critic_scores=[])
        path = save_diary(record, str(tmp_path))
        content = path.read_text(encoding="utf-8")
        assert "critic_score:" not in content

    def test_diary_text_in_body(self, tmp_path: Path) -> None:
        """日記テキストがフロントマターの後に出力される."""
        diary = "この日記はテスト用です。" * 5
        record = _make_record(diary_text=diary)
        path = save_diary(record, str(tmp_path))
        content = path.read_text(encoding="utf-8")
        assert diary in content

    def test_creates_nested_directory(self, tmp_path: Path) -> None:
        """ネストされたディレクトリが自動作成される."""
        nested = str(tmp_path / "a" / "b" / "c")
        record = _make_record()
        path = save_diary(record, nested)
        assert path.exists()

    def test_fallback_used_in_frontmatter(self, tmp_path: Path) -> None:
        """fallback_used が true/false でフロントマターに記録される."""
        record_fb = _make_record(fallback_used=True)
        path = save_diary(record_fb, str(tmp_path / "fb"))
        content = path.read_text(encoding="utf-8")
        assert "fallback_used: true" in content

        record_no_fb = _make_record(fallback_used=False)
        path2 = save_diary(record_no_fb, str(tmp_path / "nofb"))
        content2 = path2.read_text(encoding="utf-8")
        assert "fallback_used: false" in content2


# ====================================================================
# run_pipeline のテスト
# ====================================================================


class TestRunPipeline:
    """run_pipeline の終了コード分岐を検証する."""

    @pytest.mark.asyncio()
    async def test_config_error_returns_exit_config_error(self) -> None:
        """CSDGConfig の読み込み失敗で _EXIT_CONFIG_ERROR を返す."""
        args = parse_args(["--day", "1"])
        with patch("csdg.main.CSDGConfig", side_effect=Exception("missing key")):
            code = await run_pipeline(args)
        assert code == _EXIT_CONFIG_ERROR

    @pytest.mark.asyncio()
    async def test_dry_run_returns_exit_ok(self, tmp_path: Path) -> None:
        """--dry-run で _EXIT_OK を返す."""
        # prompts ディレクトリを tmp_path 配下に作成
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        for name in [
            "System_Persona.md",
            "Prompt_StateUpdate.md",
            "Prompt_Generator.md",
            "Prompt_Critic.md",
        ]:
            (prompts_dir / name).write_text("test", encoding="utf-8")

        with (
            patch("csdg.main.CSDGConfig") as mock_config_cls,
            patch("csdg.main.validate_scenario"),
        ):
            mock_config = mock_config_cls.return_value
            mock_config.output_dir = str(tmp_path)

            # run_pipeline は cwd ベースで prompts/ を探すため、Path を差し替え
            with patch("csdg.main.Path") as mock_path:
                real_path = Path

                def path_side_effect(arg: str = "") -> Path:  # type: ignore[assignment]
                    if arg == "prompts":
                        return prompts_dir
                    return real_path(arg)

                mock_path.side_effect = path_side_effect
                mock_path.cwd.return_value.resolve.return_value = tmp_path

                code = await run_pipeline(parse_args(["--dry-run"]))

        assert code == _EXIT_OK


# ====================================================================
# 終了コード定数のテスト
# ====================================================================


class TestExitCodes:
    """終了コードの定数値が functional-design.md §4.3 と一致する."""

    def test_exit_ok(self) -> None:
        assert _EXIT_OK == 0

    def test_exit_partial(self) -> None:
        assert _EXIT_PARTIAL == 1

    def test_exit_abort(self) -> None:
        assert _EXIT_ABORT == 2

    def test_exit_config_error(self) -> None:
        assert _EXIT_CONFIG_ERROR == 3
