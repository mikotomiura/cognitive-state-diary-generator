"""csdg/engine/pipeline.py のテスト。

正常系、リトライ、Temperature Decay、Best-of-N、Phase 1 フォールバック、
メモリ管理、Dayスキップ、パイプライン中断の各パターンをモックで検証する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from anthropic._exceptions import OverloadedError
from pydantic import ValidationError

from csdg.config import CSDGConfig
from csdg.engine.actor import Actor
from csdg.engine.critic import Critic, judge
from csdg.engine.pipeline import (
    PipelineRunner,
    RetryCandidate,
    _count_theme_words,
    _detect_ending_pattern,
    _detect_opening_pattern,
    _detect_scene_markers,
    _detect_structure_pattern,
    _extract_ending,
    _extract_key_images,
    _extract_opening_text,
    _extract_rhetorical_questions,
    _extract_used_philosophers,
    _sanitize_revision,
    _validate_structural_constraints,
)
from csdg.schemas import CharacterState, CriticResult, CriticScore, DailyEvent, LayerScore

if TYPE_CHECKING:
    from pathlib import Path

# ====================================================================
# ヘルパー
# ====================================================================


def _make_event(day: int, impact: float = 0.2) -> DailyEvent:
    """テスト用イベントを作成する。"""
    return DailyEvent(
        day=day,
        event_type="neutral",
        domain="仕事",
        description="社内ツールの自動化スクリプトが完成し、30分かかっていた作業が2分に短縮された",
        emotional_impact=impact,
    )


def _make_events(n: int = 7) -> list[DailyEvent]:
    """n Day 分のイベントリストを作成する。"""
    return [_make_event(d) for d in range(1, n + 1)]


def _make_pass_score() -> CriticScore:
    """合格ラインを超える CriticScore を返す。"""
    return CriticScore(temporal_consistency=4, emotional_plausibility=4, persona_deviation=5)


def _make_reject_score(
    temporal: int = 2,
    emotional: int = 4,
    persona: int = 4,
) -> CriticScore:
    """指定スコアで Reject となる CriticScore を返す。"""
    return CriticScore(
        temporal_consistency=temporal,
        emotional_plausibility=emotional,
        persona_deviation=persona,
        reject_reason="整合性が低い",
        revision_instruction="時間的整合性を改善してください",
    )


def _make_default_layer() -> LayerScore:
    """デフォルトの LayerScore を返す。"""
    return LayerScore(
        temporal_consistency=5.0,
        emotional_plausibility=5.0,
        persona_deviation=5.0,
        details={},
    )


def _wrap_as_result(score: CriticScore) -> CriticResult:
    """CriticScore を CriticResult にラップする。"""
    return CriticResult(
        rule_based=_make_default_layer(),
        statistical=_make_default_layer(),
        llm_judge=_make_default_layer(),
        final_score=score,
    )


# ====================================================================
# フィクスチャ
# ====================================================================


@pytest.fixture()
def config() -> CSDGConfig:
    return CSDGConfig(
        anthropic_api_key="test-key",
        anthropic_model="gpt-4o",
        max_retries=3,
        initial_temperature=0.7,
        output_dir="test_output",
    )


@pytest.fixture()
def state() -> CharacterState:
    return CharacterState(
        fatigue=0.1,
        motivation=0.2,
        stress=-0.1,
        current_focus="テスト",
        growth_theme="テストテーマ",
        memory_buffer=[],
        relationships={},
    )


@pytest.fixture()
def mock_actor() -> Actor:
    return AsyncMock(spec=Actor)


@pytest.fixture()
def mock_critic() -> Critic:
    return AsyncMock(spec=Critic)


@pytest.fixture()
def runner(config: CSDGConfig, mock_actor: Actor, mock_critic: Critic) -> PipelineRunner:
    return PipelineRunner(config, mock_actor, mock_critic)


# ====================================================================
# 正常系: 全7Day が1回で Pass
# ====================================================================


class TestNormalFlow:
    """正常系テスト。"""

    @pytest.mark.asyncio()
    async def test_all_days_pass_first_try(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """全7Day が1回で Pass する。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")
        # Day ごとに完全に異なるテキストを返す (trigram overlap チェック回避)
        _unique_chars = "あいうえおかきくけこさしすせそたちつてと"
        day_counter = 0

        async def _unique_diary(*args: object, **kwargs: object) -> str:
            nonlocal day_counter
            ch = _unique_chars[day_counter % len(_unique_chars)]
            day_counter += 1
            return f"{ch}の話。" + (ch * 20 + "。") * 5

        mock_actor.generate_diary.side_effect = _unique_diary
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(7)
        log = await runner.run(events, state)

        assert len(log.records) == 7
        assert log.total_retries == 0
        assert log.total_fallbacks == 0
        for record in log.records:
            assert record.retry_count == 0
            assert not record.fallback_used


# ====================================================================
# リトライ: Phase 3 で Reject → リトライで Pass
# ====================================================================


class TestRetry:
    """リトライテスト。"""

    @pytest.mark.asyncio()
    async def test_reject_then_pass_on_retry(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """Phase 3 で Reject → 2回目で Pass。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10

        reject = _make_reject_score()
        pass_score = _make_pass_score()
        mock_critic.evaluate_full.side_effect = [_wrap_as_result(reject), _wrap_as_result(pass_score)]

        event = _make_event(1)
        record = await runner.run_single_day(event, state, day=1)

        assert record.retry_count == 1
        assert len(record.critic_scores) == 2
        assert judge(record.critic_scores[-1])


# ====================================================================
# Temperature Decay: リトライ時に temperature が減衰
# ====================================================================


class TestTemperatureDecay:
    """Temperature Decay テスト。"""

    @pytest.mark.asyncio()
    async def test_temperature_decays_on_retry(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
        config: CSDGConfig,
    ) -> None:
        """リトライ時に temperature が config.temperature_schedule に従う。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10

        # 3回 Reject → Best-of-N
        reject1 = _make_reject_score(temporal=2)
        reject2 = _make_reject_score(temporal=2, emotional=3)
        reject3 = _make_reject_score(temporal=2, emotional=2)
        mock_critic.evaluate_full.side_effect = [
            _wrap_as_result(reject1),
            _wrap_as_result(reject2),
            _wrap_as_result(reject3),
        ]

        event = _make_event(1)
        record = await runner.run_single_day(event, state, day=1)

        # 全3回分のスコアが記録されている
        assert len(record.critic_scores) == 3
        # 最後に使用された temperature は最終リトライのインデックスに対応
        schedule = config.temperature_schedule
        last_attempt_idx = config.max_retries - 1
        expected_temp = schedule[last_attempt_idx] if last_attempt_idx < len(schedule) else schedule[-1]
        assert record.temperature_used == pytest.approx(expected_temp)


# ====================================================================
# Best-of-N: 3回 Reject → 最高スコア候補が選択される
# ====================================================================


class TestBestOfN:
    """Best-of-N テスト。"""

    @pytest.mark.asyncio()
    async def test_best_of_n_selects_highest_score(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """3回 Reject → CriticScore 合計が最大の候補が採用される。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")

        # 各 attempt で異なる日記テキスト
        mock_actor.generate_diary.side_effect = [
            "日記1: 低スコア",
            "日記2: 高スコア候補",
            "日記3: 中スコア",
        ]

        # スコア: attempt1=8, attempt2=10 (最大), attempt3=9
        reject1 = _make_reject_score(temporal=2, emotional=2, persona=4)  # 8
        reject2 = _make_reject_score(temporal=2, emotional=4, persona=4)  # 10
        reject3 = _make_reject_score(temporal=2, emotional=3, persona=4)  # 9
        mock_critic.evaluate_full.side_effect = [
            _wrap_as_result(reject1),
            _wrap_as_result(reject2),
            _wrap_as_result(reject3),
        ]

        event = _make_event(1)
        record = await runner.run_single_day(event, state, day=1)

        # Best-of-N で最高スコア候補 (attempt2) の日記が選択
        assert record.diary_text == "日記2: 高スコア候補"
        assert record.fallback_used is True
        assert record.retry_count == 2

    def test_select_best_candidate(self, runner: PipelineRunner) -> None:
        """_select_best_candidate のユニットテスト。"""
        state_stub = CharacterState(
            fatigue=0.0,
            motivation=0.0,
            stress=0.0,
            current_focus="x",
            growth_theme="x",
        )
        candidates = [
            RetryCandidate(
                attempt=0,
                temperature=0.7,
                state=state_stub,
                diary_text="low",
                critic_score=_make_reject_score(temporal=1, emotional=2, persona=2),
                total_score=5,
            ),
            RetryCandidate(
                attempt=1,
                temperature=0.5,
                state=state_stub,
                diary_text="high",
                critic_score=_make_reject_score(temporal=2, emotional=2, persona=4),
                total_score=8,
            ),
            RetryCandidate(
                attempt=2,
                temperature=0.3,
                state=state_stub,
                diary_text="mid",
                critic_score=_make_reject_score(temporal=2, emotional=2, persona=3),
                total_score=7,
            ),
        ]
        best = runner._select_best_candidate(candidates)
        assert best.diary_text == "high"
        assert best.total_score == 8

    @pytest.mark.asyncio()
    async def test_bonus_structural_retry_best_of_n(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """ボーナス再試行後、last-write-wins ではなく Best-of-N で最良候補を返す。

        attempt 0: Critic Pass (high score) + structural violations → ボーナス再試行
        attempt 1: Critic Pass (lower score) + no violations → break
        期待: attempt 0 の日記が返却される (total_score 15-1=14 > 12-0=12)
        """
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")

        diary_high = "DIARY_HIGH_SCORE: " + "a" * 50  # attempt 0 の日記
        diary_low = "DIARY_LOW_SCORE: " + "b" * 50   # attempt 1 (ボーナス) の日記
        mock_actor.generate_diary.side_effect = [diary_high, diary_low]

        # attempt 0: total_score=15 (5+5+5), judge Pass
        high_score = CriticScore(temporal_consistency=5, emotional_plausibility=5, persona_deviation=5)
        # attempt 1: total_score=12 (4+4+4), judge Pass
        lower_score = CriticScore(temporal_consistency=4, emotional_plausibility=4, persona_deviation=4)
        mock_critic.evaluate_full.side_effect = [
            _wrap_as_result(high_score),
            _wrap_as_result(lower_score),
        ]

        with patch(
            "csdg.engine.pipeline._validate_structural_constraints",
            side_effect=[["フック弱さ違反: 修辞疑問で閉じている"], []],
        ):
            event = _make_event(1)
            record = await runner.run_single_day(event, state, day=2)

        # Best-of-N: attempt 0 (adjusted=15-1=14) > attempt 1 (adjusted=12-0=12)
        assert record.diary_text == diary_high, (
            f"Best-of-N が機能していない: last-write-wins で {record.diary_text!r} が選ばれている"
        )
        assert not record.fallback_used
        assert record.retry_count == 1  # candidates に2つある


# ====================================================================
# Phase 1 フォールバック: ValidationError 3回 → 前日状態コピー
# ====================================================================


class TestPhase1Fallback:
    """Phase 1 フォールバックテスト。"""

    @pytest.mark.asyncio()
    async def test_validation_error_triggers_fallback(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """ValidationError 3回 → 前日状態コピーがフォールバックとして使用される。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        mock_actor.update_state.side_effect = ValidationError.from_exception_data(
            title="CharacterState",
            line_errors=[
                {
                    "type": "value_error",
                    "loc": ("stress",),
                    "msg": "test error",
                    "input": 999,
                    "ctx": {"error": ValueError("test error")},
                },
            ],
        )
        mock_actor.generate_diary.return_value = "フォールバック日記" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        event = _make_event(1)
        record = await runner.run_single_day(event, state, day=1)

        assert record.fallback_used is True
        # 前日状態のパラメータが引き継がれている
        assert record.final_state.stress == state.stress
        assert record.final_state.motivation == state.motivation
        # memory_buffer にフォールバック情報が含まれる
        assert any("フォールバック" in m for m in record.final_state.memory_buffer)


# ====================================================================
# memory_buffer: Day 5 で buffer が直近3Day分になること
# ====================================================================


class TestMemoryBuffer:
    """memory_buffer テスト。"""

    @pytest.mark.asyncio()
    async def test_sliding_window_via_run(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """run() 経由で memory_buffer が update_state に渡されること。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        # update_state が prev_state の memory_buffer を引き継ぐモック
        async def _update_preserving_memory(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> CharacterState:
            return (prev.model_copy(update={"stress": 0.0}), "テストreason")

        mock_actor.update_state.side_effect = _update_preserving_memory
        mock_actor.generate_diary.return_value = "テスト日記です。" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(5)
        log = await runner.run(events, state)

        assert len(log.records) == 5
        # Day 5 の update_state 呼び出し時、prev_state に memory_buffer が注入されている
        # (run() が _update_memory_buffer で current_state を更新してから次 Day に渡すため)
        day5_call = mock_actor.update_state.call_args_list[4]
        prev_state_at_day5 = day5_call.args[0]
        # window_size=3 なので Day2, Day3, Day4 の要約が残る
        assert len(prev_state_at_day5.memory_buffer) == 3
        assert "[Day 2]" in prev_state_at_day5.memory_buffer[0]
        assert "[Day 3]" in prev_state_at_day5.memory_buffer[1]
        assert "[Day 4]" in prev_state_at_day5.memory_buffer[2]

    # _update_memory_buffer は MemoryManager に移行済みのため、
    # スライディングウィンドウのテストは test_memory.py を参照。


# ====================================================================
# Dayスキップ: 予期しない例外 → 該当Day スキップ、次Day 実行
# ====================================================================


class TestDaySkip:
    """Dayスキップテスト。"""

    @pytest.mark.asyncio()
    async def test_unexpected_exception_skips_day(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """予期しない例外で該当Day がスキップされ、次Day が実行される。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        call_count = 0

        async def update_state_side_effect(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            nonlocal call_count
            call_count += 1
            if event.day == 3:
                raise RuntimeError("予期しないエラー")
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_state_side_effect
        mock_actor.generate_diary.return_value = "日記テキスト" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(5)
        log = await runner.run(events, state)

        # Day 3 がスキップされるので 4 件
        assert len(log.records) == 4
        recorded_days = [r.day for r in log.records]
        assert 3 not in recorded_days


# ====================================================================
# パイプライン中断: 連続3Day失敗 → 中断
# ====================================================================


class TestPipelineAbort:
    """パイプライン中断テスト。"""

    @pytest.mark.asyncio()
    async def test_abort_after_3_consecutive_failures(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """連続3Day失敗 → パイプライン中断、生成済み成果物が PipelineLog に含まれる。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})

        async def update_state_side_effect(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            if event.day >= 3:
                raise RuntimeError("連続失敗シミュレーション")
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_state_side_effect
        mock_actor.generate_diary.return_value = "日記テキスト" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(7)
        log = await runner.run(events, state)

        # Day 1, 2 は成功、Day 3, 4, 5 で連続失敗して中断
        # Day 6, 7 は実行されない
        assert len(log.records) == 2
        assert log.records[0].day == 1
        assert log.records[1].day == 2


# ====================================================================
# prompt_hashes: プロンプトファイルのハッシュ計算
# ====================================================================


class TestPromptHashes:
    """prompt_hashes テスト。"""

    def test_compute_prompt_hashes_with_files(self, tmp_path: Path) -> None:
        """プロンプトファイルが存在する場合、ハッシュが計算される。"""
        (tmp_path / "System_Persona.md").write_text("persona", encoding="utf-8")
        (tmp_path / "Prompt_Generator.md").write_text("generator", encoding="utf-8")

        hashes = PipelineRunner._compute_prompt_hashes(tmp_path)

        assert len(hashes) == 2
        assert "System_Persona.md" in hashes
        assert "Prompt_Generator.md" in hashes
        for _name, h in hashes.items():
            assert len(h) == 64  # SHA-256 hex length
            assert all(c in "0123456789abcdef" for c in h)

    def test_compute_prompt_hashes_empty_dir(self, tmp_path: Path) -> None:
        """空ディレクトリではハッシュが空辞書。"""
        hashes = PipelineRunner._compute_prompt_hashes(tmp_path)
        assert hashes == {}

    def test_compute_prompt_hashes_nonexistent_dir(self, tmp_path: Path) -> None:
        """存在しないディレクトリではハッシュが空辞書。"""
        hashes = PipelineRunner._compute_prompt_hashes(tmp_path / "nonexistent")
        assert hashes == {}

    @pytest.mark.asyncio()
    async def test_pipeline_log_contains_prompt_hashes(
        self,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
        tmp_path: Path,
    ) -> None:
        """PipelineLog.prompt_hashes にハッシュ値が含まれる。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        (tmp_path / "Test.md").write_text("test prompt", encoding="utf-8")
        cfg = CSDGConfig(
            anthropic_api_key="test-key",
            anthropic_model="gpt-4o",
            max_retries=3,
            initial_temperature=0.7,
            output_dir="test_output",
        )
        runner = PipelineRunner(cfg, mock_actor, mock_critic, prompts_dir=tmp_path)

        updated = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated, "テストreason")
        mock_actor.generate_diary.return_value = "日記テキスト" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        log = await runner.run([_make_event(1)], state)

        assert "Test.md" in log.prompt_hashes
        assert len(log.prompt_hashes["Test.md"]) == 64


# ====================================================================
# 統合ギャップ修正: llm_client、長期記憶注入、CriticLog 永続化
# ====================================================================


class TestIntegrationGapFixes:
    """統合ギャップ修正のテスト。"""

    def test_pipeline_runner_accepts_llm_client(
        self,
        config: CSDGConfig,
        mock_actor: Actor,
        mock_critic: Critic,
    ) -> None:
        """PipelineRunner が llm_client パラメータを受け入れる。"""
        mock_client = AsyncMock()
        runner = PipelineRunner(config, mock_actor, mock_critic, llm_client=mock_client)
        assert runner._llm_client is mock_client

    @pytest.mark.asyncio()
    async def test_llm_client_passed_to_memory_update(
        self,
        config: CSDGConfig,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """run() が memory.update_after_day() に llm_client を渡す。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        mock_client = AsyncMock()
        runner = PipelineRunner(config, mock_actor, mock_critic, llm_client=mock_client)

        updated = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated, "テストreason")
        mock_actor.generate_diary.return_value = "テスト日記" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        # MemoryManager.update_after_day をモックして llm_client が渡されるか検証
        with patch.object(runner._memory, "update_after_day", new_callable=AsyncMock) as mock_update:
            await runner.run([_make_event(1)], state)
            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args
            assert call_kwargs.kwargs.get("llm_client") is mock_client

    @pytest.mark.asyncio()
    async def test_long_term_context_passed_to_actor(
        self,
        config: CSDGConfig,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """run_single_day() が Actor に long_term_context を渡す。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        runner = PipelineRunner(config, mock_actor, mock_critic)

        updated = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated, "テストreason")
        mock_actor.generate_diary.return_value = "テスト日記" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        await runner.run_single_day(_make_event(1), state, day=1)

        # update_state に long_term_context が渡されている
        update_call = mock_actor.update_state.call_args
        assert "long_term_context" in update_call.kwargs

        # generate_diary に long_term_context が渡されている
        diary_call = mock_actor.generate_diary.call_args
        assert "long_term_context" in diary_call.kwargs

    def test_critic_log_property(
        self,
        runner: PipelineRunner,
    ) -> None:
        """PipelineRunner.critic_log プロパティが CriticLog を返す。"""
        from csdg.engine.critic_log import CriticLog

        assert isinstance(runner.critic_log, CriticLog)


# ====================================================================
# OverloadedError リトライ: API 過負荷時にパイプラインレベルでリトライ
# ====================================================================


def _make_overloaded_error() -> OverloadedError:
    """テスト用の OverloadedError を作成する。"""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(
        529,
        json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        request=req,
    )
    return OverloadedError(message="Overloaded", response=resp, body=None)


class TestOverloadedRetry:
    """OverloadedError パイプラインレベルリトライのテスト。"""

    @pytest.mark.asyncio()
    async def test_overloaded_error_retries_same_day(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """OverloadedError が一時的に発生しても、リトライで同一 Day が成功する。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        call_count = 0

        async def update_state_with_transient_overload(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            nonlocal call_count
            call_count += 1
            # Day 1 の最初の2回は OverloadedError、3回目で成功
            if event.day == 1 and call_count <= 2:
                raise _make_overloaded_error()
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_state_with_transient_overload
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = [_make_event(1)]
        with patch("csdg.engine.pipeline.asyncio.sleep", new_callable=AsyncMock):
            log = await runner.run(events, state)

        # Day 1 が成功している
        assert len(log.records) == 1
        assert log.records[0].day == 1

    @pytest.mark.asyncio()
    async def test_overloaded_error_does_not_count_as_consecutive_failure(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """OverloadedError のリトライで回復した場合、consecutive_failures にカウントされない。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        call_count = 0

        async def update_with_overload_on_day2(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            nonlocal call_count
            call_count += 1
            # Day 2 で1回 OverloadedError、リトライで成功
            if event.day == 2 and call_count == 2:
                raise _make_overloaded_error()
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_with_overload_on_day2
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(3)
        with patch("csdg.engine.pipeline.asyncio.sleep", new_callable=AsyncMock):
            log = await runner.run(events, state)

        # 全3Day 成功 (OverloadedError は回復したので連続失敗にならない)
        assert len(log.records) == 3

    @pytest.mark.asyncio()
    async def test_overloaded_error_exhausts_retries_then_skips(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """OverloadedError がリトライ上限を超えた場合、Day スキップとなる。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})

        async def update_always_overloaded_on_day2(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            if event.day == 2:
                raise _make_overloaded_error()
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_always_overloaded_on_day2
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(4)
        with patch("csdg.engine.pipeline.asyncio.sleep", new_callable=AsyncMock):
            log = await runner.run(events, state)

        # Day 2 はスキップされ、Day 1, 3, 4 が成功
        assert len(log.records) == 3
        recorded_days = [r.day for r in log.records]
        assert 2 not in recorded_days
        assert recorded_days == [1, 3, 4]

    @pytest.mark.asyncio()
    async def test_other_exceptions_not_retried(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """OverloadedError 以外の例外はリトライされずに即 Day スキップ。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})

        async def update_runtime_error_on_day2(
            prev: CharacterState,
            event: DailyEvent,
            long_term_context: dict | None = None,
        ) -> tuple[CharacterState, str]:
            if event.day == 2:
                raise RuntimeError("予期しないエラー")
            return (updated_state, "テストreason")

        mock_actor.update_state.side_effect = update_runtime_error_on_day2
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(3)
        log = await runner.run(events, state)

        # Day 2 がスキップ、Day 1 と 3 は成功
        assert len(log.records) == 2
        recorded_days = [r.day for r in log.records]
        assert 2 not in recorded_days


# ====================================================================
# _extract_ending: 末尾段落の抽出
# ====================================================================


class TestExtractEnding:
    """_extract_ending のテスト。"""

    def test_multiple_paragraphs(self) -> None:
        text = "段落1。\n\n段落2。\n\n最後の余韻......。"
        assert _extract_ending(text) == "最後の余韻......。"

    def test_single_paragraph(self) -> None:
        text = "これが唯一の段落です。"
        assert _extract_ending(text) == "これが唯一の段落です。"

    def test_empty_string(self) -> None:
        assert _extract_ending("") == ""

    def test_trailing_whitespace(self) -> None:
        text = "段落1。\n\n余韻......。\n\n"
        assert _extract_ending(text) == "余韻......。"


# ====================================================================
# _sanitize_revision: 修正指示のサニタイズ
# ====================================================================


class TestSanitizeRevision:
    """_sanitize_revision のテスト。"""

    def test_none_returns_none(self) -> None:
        """None 入力は None を返す。"""
        assert _sanitize_revision(None) is None

    def test_wraps_in_revision_tags(self) -> None:
        """非 None 入力は <revision> タグで囲まれる。"""
        result = _sanitize_revision("修正してください")
        assert result is not None
        assert result.startswith("<revision>")
        assert result.endswith("</revision>")
        assert "修正してください" in result

    def test_truncates_at_limit(self) -> None:
        """500文字を超える入力は切り詰められる。"""
        long_text = "あ" * 600
        result = _sanitize_revision(long_text)
        assert result is not None
        # タグ部分を除いた中身が500文字以下
        inner = result.replace("<revision>\n", "").replace("\n</revision>", "")
        assert len(inner) <= 500

    def test_control_characters_removed(self) -> None:
        """制御文字 (改行・タブ以外) が除去される。"""
        text_with_ctrl = "修正\x00して\x01ください"
        result = _sanitize_revision(text_with_ctrl)
        assert result is not None
        assert "\x00" not in result
        assert "\x01" not in result
        assert "修正してください" in result

    def test_newlines_and_tabs_preserved(self) -> None:
        """改行とタブは除去されない。"""
        text = "行1\n行2\t値"
        result = _sanitize_revision(text)
        assert result is not None
        assert "\n行2" in result
        assert "\t値" in result


# ====================================================================
# prev_endings の蓄積と受け渡し
# ====================================================================


class TestPrevEndingsTracking:
    """prev_endings の蓄積と generate_diary への受け渡しテスト。"""

    @pytest.mark.asyncio()
    async def test_prev_endings_passed_to_generate_diary(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """run() が generate_diary に prev_endings を渡す。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")
        mock_actor.generate_diary.return_value = "段落1。\n\n余韻A......。"
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(2)
        await runner.run(events, state)

        # Day 2 の generate_diary 呼び出しで prev_endings が渡されている
        day2_call = mock_actor.generate_diary.call_args_list[1]
        assert "prev_endings" in day2_call.kwargs
        assert len(day2_call.kwargs["prev_endings"]) == 1
        assert "余韻A" in day2_call.kwargs["prev_endings"][0]

    @pytest.mark.asyncio()
    async def test_prev_endings_limited_to_3(
        self,
        runner: PipelineRunner,
        mock_actor: Actor,
        mock_critic: Critic,
        state: CharacterState,
    ) -> None:
        """prev_endings は直近3件に制限される。"""
        assert isinstance(mock_actor, AsyncMock)
        assert isinstance(mock_critic, AsyncMock)

        updated_state = state.model_copy(update={"stress": 0.0})
        mock_actor.update_state.return_value = (updated_state, "テストreason")

        # Day ごとに完全に異なるテキストを返す (構造的制約違反を回避)
        # 書き出し・余韻パターンが全Day で異なるようにする
        _unique_texts = [
            "まるで空のように広がる朝の光景を眺めながら考えた一日目の物語が続く。\n\nこれは本当に自分の選択なのだろうか......",
            "「昨日の話だけど」と那由他が言った声が耳に残る二日目の午後である。\n\n窓辺に置かれた花瓶の水が光を反射していた。",
            "雨上がりの街角で濡れた石畳の匂いが鼻をかすめた三日目の散歩道。\n\n傘を畳んで鞄にしまい、電車に乗り込んだ。",
            "あの日のことを思い出す——窓辺に座って遠くの山を眺めていた四日目。\n\n珈琲の残り香。",
            "効率とは何か——友人との再会が心に波紋を広げた五日目の夕暮れ時。\n\nそれは、ただの思い込みなのかもしれない。",
        ]
        day_idx = 0

        async def generate_with_unique_ending(
            *args: object,
            **kwargs: object,
        ) -> str:
            nonlocal day_idx
            text = _unique_texts[day_idx % len(_unique_texts)]
            day_idx += 1
            return text

        mock_actor.generate_diary.side_effect = generate_with_unique_ending
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(5)
        await runner.run(events, state)

        # Day 5 の呼び出しで prev_endings が3件に制限されている
        day5_call = mock_actor.generate_diary.call_args_list[4]
        prev_endings = day5_call.kwargs["prev_endings"]
        assert len(prev_endings) == 3
        # Day 2, 3, 4 の余韻が保持されている (Day 1 は window 外)
        assert "花瓶" in prev_endings[0]  # Day 2
        assert "電車" in prev_endings[1]  # Day 3
        assert "珈琲" in prev_endings[2]  # Day 4: 体言止め系


# ====================================================================
# _extract_key_images: シーン描写の抽出
# ====================================================================


class TestExtractKeyImages:
    """_extract_key_images のテスト。"""

    def test_extracts_scene_markers(self) -> None:
        """シーンマーカーを含む文が抽出される。"""
        text = "帰り道、古書店に立ち寄った。店主が手書きでポップを書いている。"
        images = _extract_key_images(text)
        assert len(images) >= 1
        assert any("古書店" in img for img in images)

    def test_deduplicates_same_marker(self) -> None:
        """同一マーカーが複数文に現れても1回のみ抽出される。"""
        # 「窓」マーカーが2文に現れるが、1回目のみ抽出
        text = "窓の外を見た。もう一度窓に目を向けた。"
        images = _extract_key_images(text)
        window_imgs = [img for img in images if "窓" in img]
        assert len(window_imgs) == 1

    def test_max_images_limit(self) -> None:
        """最大件数で制限される。"""
        text = (
            "古書店に行った。電車に乗った。コンビニで買った。"
            "会議室で話した。窓の外を見た。カフェに入った。"
            "蛍光灯が光る。ノートを開いた。"
        )
        images = _extract_key_images(text, max_images=3)
        assert len(images) <= 3

    def test_empty_text_returns_empty(self) -> None:
        """空テキストで空リスト。"""
        assert _extract_key_images("") == []

    def test_no_markers_returns_empty(self) -> None:
        """マーカーを含まないテキストで空リスト。"""
        assert _extract_key_images("今日は良い天気だった。哲学について考えた。") == []


# ====================================================================
# _detect_opening_pattern: 書き出しパターンの分類
# ====================================================================


class TestDetectOpeningPattern:
    """_detect_opening_pattern のテスト。"""

    def test_metaphor_pattern(self) -> None:
        """比喩型の検出。"""
        assert _detect_opening_pattern("今日は、まるでカフカの変身のような一日だった。") == "比喩型"

    def test_dialogue_pattern(self) -> None:
        """会話型の検出。"""
        assert _detect_opening_pattern("\u300cで、それ実装できるの\uff1f\u300d\u2014\u2014那由他さんの声が") == "会話型"

    def test_sensory_pattern(self) -> None:
        """五感型の検出。"""
        assert _detect_opening_pattern("図書館のインクの匂いが、鼻の奥にまだ残っている。") == "五感型"

    def test_recall_pattern(self) -> None:
        """回想型の検出。"""
        assert _detect_opening_pattern("大学院の研究室には、いつも珈琲の香りが漂っていた。") == "回想型"

    def test_fragment_pattern(self) -> None:
        """断片型の検出 (短い冒頭)。"""
        assert _detect_opening_pattern("会議。沈黙。憂鬱。") == "断片型"

    def test_empty_text(self) -> None:
        """空テキストでその他。"""
        assert _detect_opening_pattern("") == "その他"

    def test_question_pattern(self) -> None:
        """問い型の検出。"""
        result = _detect_opening_pattern("効率って、いつから美徳になったんだろうか")
        assert result == "問い型"

    def test_skips_date_heading(self) -> None:
        """日付見出し行をスキップして実際の書き出しを判定する。"""
        text = "# 2026年12月2日\n\n今日は、まるでベルトコンベアの上で立ち尽くしているような一日だった。"
        assert _detect_opening_pattern(text) == "比喩型"

    def test_skips_markdown_heading(self) -> None:
        """Markdown見出し行をスキップする。"""
        text = "## 日記\n\n「で、それ実装できるの？」——那由他さんの声が響いた。"
        assert _detect_opening_pattern(text) == "会話型"

    def test_skips_empty_lines_after_heading(self) -> None:
        """見出し後の空行もスキップする。"""
        text = "# タイトル\n\n\n図書館のインクの匂いが、鼻の奥にまだ残っている。"
        assert _detect_opening_pattern(text) == "五感型"

    def test_conversation_echo_with_voice(self) -> None:
        """「人名+声が」パターンが会話型として検出される (五感型より優先)。"""
        assert _detect_opening_pattern("那由他さんの声が、まだ耳に残っている。") == "会話型"

    def test_conversation_echo_with_words(self) -> None:
        """「人名+言葉が」パターンが会話型として検出される。"""
        assert _detect_opening_pattern("ミナちゃんの言葉が、胸の奥で響いている。") == "会話型"

    def test_conversation_echo_with_single_word(self) -> None:
        """「人名+一言が」パターンが会話型として検出される。"""
        assert _detect_opening_pattern("先生の一言が、まだ頭の中を駆け巡っている。") == "会話型"

    def test_pure_sensory_voice_not_overridden(self) -> None:
        """人名を伴わない「声」は五感型のまま。"""
        assert _detect_opening_pattern("遠くで聞こえる声が、静かな夜を揺らした。") == "五感型"


# ====================================================================
# _detect_structure_pattern: 場面構造パターンの分類
# ====================================================================


class TestDetectStructurePattern:
    """_detect_structure_pattern のテスト。"""

    def test_kiroji_pattern(self) -> None:
        """帰路型の検出 (2つ以上のマーカー一致)。"""
        text = "帰り道に電車に乗った。窓の外を眺める。"
        assert _detect_structure_pattern(text) == "帰路型"

    def test_kiroji_single_marker_matched(self) -> None:
        """帰路型はマーカー1つで検出される."""
        text = "帰り道を歩いた。カフェに立ち寄った。"
        assert _detect_structure_pattern(text) == "帰路型"

    def test_kaerino_densha_detected(self) -> None:
        """「帰りの電車」で帰路型検出."""
        text = "帰りの電車で考えた。窓の外は暗かった。"
        assert _detect_structure_pattern(text) == "帰路型"

    def test_koshotan_pattern(self) -> None:
        """古書店型の検出。"""
        text = "古書店の明かりが目に入った。"
        assert _detect_structure_pattern(text) == "古書店型"

    def test_kaigi_pattern(self) -> None:
        """会議型の検出。"""
        text = "会議室でプレゼンをした。"
        assert _detect_structure_pattern(text) == "会議型"

    def test_other_pattern(self) -> None:
        """その他パターン。"""
        text = "今日はカフェでコーヒーを飲みながら本を読んだ。"
        assert _detect_structure_pattern(text) == "その他"

    def test_empty_text(self) -> None:
        """空テキストはその他。"""
        assert _detect_structure_pattern("") == "その他"


# ====================================================================
# _extract_used_philosophers: 哲学者抽出
# ====================================================================


class TestExtractUsedPhilosophers:
    """_extract_used_philosophers のテスト。"""

    def test_single_philosopher(self) -> None:
        """1人の哲学者を検出。"""
        text = "西田幾多郎の純粋経験について考えた。"
        result = _extract_used_philosophers(text)
        assert result == ["西田幾多郎"]

    def test_multiple_philosophers(self) -> None:
        """複数の哲学者を検出。"""
        text = "ハイデガーの存在論とカフカの変身を比較した。"
        result = _extract_used_philosophers(text)
        assert "ハイデガー" in result
        assert "カフカ" in result

    def test_no_philosopher(self) -> None:
        """哲学者の言及なし。"""
        text = "今日は普通の一日だった。"
        result = _extract_used_philosophers(text)
        assert result == []

    def test_empty_text(self) -> None:
        """空テキスト。"""
        assert _extract_used_philosophers("") == []


# ====================================================================
# 余韻末尾パターン分類 (_detect_ending_pattern)
# ====================================================================


class TestDetectEndingPattern:
    """_detect_ending_pattern のテスト。"""

    def test_daroo_pattern(self) -> None:
        """「〜だろう」系を検出する。"""
        text = "段落1。\n\nこの本は何を知っているのだろう......"
        assert _detect_ending_pattern(text) == "〜だろう系"

    def test_darouka_pattern(self) -> None:
        """「〜だろうか」系を検出する。"""
        text = "段落1。\n\nそれは果たして正しいのだろうか。"
        assert _detect_ending_pattern(text) == "〜だろう系"

    def test_kamoshirenai_pattern(self) -> None:
        """「〜かもしれない」系を検出する。"""
        text = "段落1。\n\nそれは幻想なのかもしれない......"
        assert _detect_ending_pattern(text) == "〜かもしれない系"

    def test_zuniiiru_pattern(self) -> None:
        """「〜ずにいる」系を検出する。"""
        text = "段落1。\n\nペンを握ったまま、最初の一文字を書けずにいる......"
        assert _detect_ending_pattern(text) == "〜ずにいる系"

    def test_teinai_pattern(self) -> None:
        """「〜ていない」系を検出する。"""
        text = "段落1。\n\nわたしはまだ、その答えを見つけていない......"
        assert _detect_ending_pattern(text) == "〜ずにいる系"

    def test_generic_iru_returns_ellipsis(self) -> None:
        """汎用的な「〜いる」+ 「......」は省略系を返す。"""
        text = "段落1。\n\nわたしはまだ、図書館にいる......"
        assert _detect_ending_pattern(text) == "省略系"

    def test_teita_returns_teiru(self) -> None:
        """「〜ていた」は〜ている系を返す。"""
        text = "段落1。\n\n窓の外に、雨が降っていた。"
        assert _detect_ending_pattern(text) == "〜ている系"

    def test_other_pattern(self) -> None:
        """その他パターンを返す。"""
        text = "段落1。\n\nゆっくりと深呼吸をした。"
        assert _detect_ending_pattern(text) == "その他"

    def test_empty_text(self) -> None:
        """空テキストはその他を返す。"""
        assert _detect_ending_pattern("") == "その他"


# ====================================================================
# 主題語カウント (_count_theme_words)
# ====================================================================


class TestCountThemeWords:
    """_count_theme_words のテスト。"""

    def test_counts_correctly(self) -> None:
        """主題語が正しくカウントされる。"""
        text = "効率化を求める社会。最適化の波。自動化の未来。"
        counts = _count_theme_words(text)
        assert counts["効率"] == 1
        assert counts["最適化"] == 1
        assert counts["自動化"] == 1

    def test_multiple_occurrences(self) -> None:
        """同一語の複数出現をカウントする。"""
        text = "効率と効率の対立。効率という名の呪縛。"
        counts = _count_theme_words(text)
        assert counts["効率"] == 3

    def test_empty_text(self) -> None:
        """空テキストは全て0。"""
        counts = _count_theme_words("")
        assert all(v == 0 for v in counts.values())

    def test_no_theme_words(self) -> None:
        """主題語が含まれないテキスト。"""
        text = "今日は穏やかな一日だった。"
        counts = _count_theme_words(text)
        assert all(v == 0 for v in counts.values())


# ====================================================================
# 修辞疑問文抽出 (_extract_rhetorical_questions)
# ====================================================================


class TestExtractRhetoricalQuestions:
    """_extract_rhetorical_questions のテスト。"""

    def test_extracts_nani_question(self) -> None:
        """「〜って、何」パターンを抽出する。"""
        text = "効率って、何のため？　その問いが頭の片隅で響く。"
        questions = _extract_rhetorical_questions(text)
        assert len(questions) >= 1

    def test_extracts_nitaishite_question(self) -> None:
        """「〜に対して？」パターンを抽出する。"""
        text = "非効率的って、何に対して？ 利益に対して？ 時間に対して？"
        questions = _extract_rhetorical_questions(text)
        assert len(questions) >= 1

    def test_max_questions_limit(self) -> None:
        """最大数を超えない。"""
        text = (
            "効率って、何のため？ "
            "速さって、何のため？ "
            "正確さって、何のため？ "
            "利便性って、何のため？ "
            "進歩って、何のため？ "
            "成長って、何のため？ "
        )
        questions = _extract_rhetorical_questions(text, max_questions=3)
        assert len(questions) <= 3

    def test_empty_text(self) -> None:
        """空テキストは空リスト。"""
        assert _extract_rhetorical_questions("") == []

    def test_no_rhetorical(self) -> None:
        """修辞疑問文がないテキスト。"""
        text = "今日も穏やかな一日が過ぎていった。"
        assert _extract_rhetorical_questions(text) == []

    def test_truncates_to_50_chars(self) -> None:
        """50文字を超える修辞疑問文が切り詰められる。"""
        text = "あ" * 40 + "って、何のため？"
        questions = _extract_rhetorical_questions(text)
        if questions:
            assert all(len(q) <= 50 for q in questions)

    def test_darouka_pattern(self) -> None:
        """「〜のだろうか」パターンを抽出する。"""
        text = "この二つは本当に対立するものなのだろうか。"
        questions = _extract_rhetorical_questions(text)
        assert len(questions) >= 1

    def test_nanoka_pattern(self) -> None:
        """「〜なのか」パターンを抽出する。"""
        text = "迷いのない思考って、それ本当に思考なのか。"
        questions = _extract_rhetorical_questions(text)
        assert len(questions) >= 1


# ====================================================================
# シーンマーカー検出 (_detect_scene_markers)
# ====================================================================


class TestDetectSceneMarkers:
    """_detect_scene_markers のテスト。"""

    def test_detects_single_marker(self) -> None:
        """単一マーカーを検出する。"""
        text = "蛍光灯の下で、わたしは一冊の本を読んでいた。"
        markers = _detect_scene_markers(text)
        assert "蛍光灯" in markers

    def test_detects_multiple_markers(self) -> None:
        """複数マーカーを検出する。"""
        text = "古書店の蛍光灯の下で、キーボードを叩いていた。"
        markers = _detect_scene_markers(text)
        assert "古書店" in markers
        assert "蛍光灯" in markers
        assert "キーボード" in markers

    def test_no_markers(self) -> None:
        """マーカーなし。"""
        text = "今日は穏やかな一日だった。"
        markers = _detect_scene_markers(text)
        assert len(markers) == 0

    def test_empty_text(self) -> None:
        """空テキスト。"""
        assert _detect_scene_markers("") == set()

    def test_returns_set(self) -> None:
        """重複なしの集合を返す。"""
        text = "蛍光灯が照らす。蛍光灯の光。また蛍光灯。"
        markers = _detect_scene_markers(text)
        assert isinstance(markers, set)
        assert markers == {"蛍光灯"}


# ====================================================================
# _SCENE_MARKERS の整合性テスト
# ====================================================================


class TestSceneMarkersIntegrity:
    """_SCENE_MARKERS の弁別力テスト。"""

    def test_removed_markers_not_present(self) -> None:
        """除外されたマーカーが含まれていないこと。"""
        from csdg.engine.pipeline import _SCENE_MARKERS

        removed = ("本", "道", "匂い", "明かり")
        for marker in removed:
            assert marker not in _SCENE_MARKERS, f"除外されるべきマーカー '{marker}' が残っている"

    def test_added_markers_present(self) -> None:
        """追加されたマーカーが含まれていること。"""
        from csdg.engine.pipeline import _SCENE_MARKERS

        added = (
            "万年筆",
            "茶碗",
            "珈琲",
            "インク",
            "背表紙",
            "付箋",
            "マグカップ",
            "手帳",
            "傘",
            "湯気",
            "古本",
            "夕焼け",
        )
        for marker in added:
            assert marker in _SCENE_MARKERS, f"追加されるべきマーカー '{marker}' が存在しない"

    def test_no_low_discriminability_single_char(self) -> None:
        """弁別力不足の1文字マーカー (本/道) が含まれないこと。"""
        from csdg.engine.pipeline import _SCENE_MARKERS

        low_discriminability = {"本", "道"}
        for marker in low_discriminability:
            assert marker not in _SCENE_MARKERS, f"弁別力不足のマーカー '{marker}' が残っている"


# ====================================================================
# _extract_key_images の弁別力テスト
# ====================================================================


class TestExtractKeyImagesBenbelryoku:
    """_extract_key_images の誤検出防止テスト。"""

    def test_hon_false_positive_avoided(self) -> None:
        """「本当に」を含むテキストで「本」が検出されないこと。"""
        text = "本当にそうなのか、わたしにはわからない。本質的な問いだと思った。"
        images = _extract_key_images(text)
        assert not any("本当" in img or "本質" in img for img in images) or len(images) == 0

    def test_michi_false_positive_avoided(self) -> None:
        """「道具」「道理」を含むテキストで「道」が検出されないこと。"""
        text = "道具を揃えることが道理だと思った。"
        images = _extract_key_images(text)
        assert len(images) == 0

    def test_mannenhitsu_ink_detected(self) -> None:
        """「万年筆のインクが乾いていた」で「万年筆」「インク」が検出されること。"""
        text = "万年筆のインクが乾いていた。ノートを開いて書き始める。"
        images = _extract_key_images(text)
        marker_words = " ".join(images)
        assert "万年筆" in marker_words
        assert "インク" in marker_words

    def test_furuhon_sehyoushi_detected(self) -> None:
        """「古本の背表紙を撫でた」で「古本」「背表紙」が検出されること。"""
        text = "古本の背表紙を撫でた。栞が挟んであった。"
        images = _extract_key_images(text)
        marker_words = " ".join(images)
        assert "古本" in marker_words
        assert "背表紙" in marker_words


# ====================================================================
# 余韻分類の新パターンテスト
# ====================================================================


class TestDetectEndingPatternExpanded:
    """_detect_ending_pattern の拡張パターンテスト。"""

    def test_teiru_pattern(self) -> None:
        """「〜ている」系を検出する。"""
        text = "段落1。\n\nあの音が、まだ鳴っている。"
        assert _detect_ending_pattern(text) == "〜ている系"

    def test_teita_pattern(self) -> None:
        """「〜ていた」系を検出する。"""
        text = "段落1。\n\n窓の外では雨が降っていた。"
        assert _detect_ending_pattern(text) == "〜ている系"

    def test_action_pattern(self) -> None:
        """行動締め系を検出する。"""
        text = "段落1。\n\nノートを閉じて、電気を消した。"
        assert _detect_ending_pattern(text) == "行動締め系"

    def test_quote_pattern(self) -> None:
        """引用系を検出する。"""
        text = "段落1。\n\n『問いのない思考は情報処理だ』——その言葉が耳に残る。"
        assert _detect_ending_pattern(text) == "引用系"

    def test_taigendome_pattern(self) -> None:
        """体言止め系を検出する。"""
        text = "段落1。\n\n窓の外に落ちる、最後の残照。"
        assert _detect_ending_pattern(text) == "体言止め系"

    def test_ellipsis_pattern(self) -> None:
        """省略系を検出する。"""
        text = "段落1。\n\n明日のわたしは、きっと......"
        assert _detect_ending_pattern(text) == "省略系"

    def test_other_remains(self) -> None:
        """既存の「その他」判定が維持される。"""
        text = "段落1。\n\n今日はここまでにしておく。"
        assert _detect_ending_pattern(text) == "その他"

    def test_existing_daroo_preserved(self) -> None:
        """既存の「〜だろう系」判定が維持される。"""
        text = "段落1。\n\nこの本は何を知っているのだろう......"
        assert _detect_ending_pattern(text) == "〜だろう系"

    def test_existing_zuniiiru_preserved(self) -> None:
        """既存の「〜ずにいる系」判定が維持される。"""
        text = "段落1。\n\nペンを握ったまま、最初の一文字を書けずにいる......"
        assert _detect_ending_pattern(text) == "〜ずにいる系"


# ====================================================================
# 構造的制約バリデーション (_validate_structural_constraints)
# ====================================================================


class TestValidateStructuralConstraints:
    """_validate_structural_constraints のテスト。"""

    def test_no_violations(self) -> None:
        """制約違反がない場合は空リストを返す。"""
        text = "段落1。\n\nそれは幻想なのかもしれない......"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=["Day 1: 〜だろう系"],
            used_structures=["Day 1: 古書店型"],
            used_openings=["Day 1: 比喩型"],
            theme_word_totals={"効率": 2},
        )
        assert violations == []

    def test_ending_pattern_violation(self) -> None:
        """余韻パターンが上限 (2回) に達している場合に違反を検出する。"""
        text = "段落1。\n\nこの本は何を知っているのだろう......"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=["Day 1: 〜だろう系", "Day 2: 〜だろう系"],
            used_structures=[],
            used_openings=[],
            theme_word_totals={},
        )
        assert len(violations) == 1
        assert "〜だろう系" in violations[0]

    def test_consecutive_structure_violation(self) -> None:
        """前日と同じ場面構造パターンで違反を検出する。"""
        text = "会議室で蛍光灯の下、議論が続いた。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=["Day 1: 会議型"],
            used_openings=[],
            theme_word_totals={},
        )
        assert any("前日と同じ" in v for v in violations)

    def test_structure_limit_violation(self) -> None:
        """場面構造パターンが上限に達している場合に違反を検出する。"""
        text = "会議室で蛍光灯の下、議論が続いた。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=["Day 1: 会議型", "Day 2: 古書店型", "Day 3: 会議型", "Day 4: その他", "Day 5: 会議型"],
            used_openings=[],
            theme_word_totals={},
        )
        assert any("上限" in v and "会議型" in v for v in violations)

    def test_theme_word_violation(self) -> None:
        """主題語が per-day 上限を超過した場合に違反を検出する。"""
        text = "効率化を求め、効率を追い、効率に疲れ、効率の呪縛。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=[],
            used_openings=[],
            theme_word_totals={"効率": 5},
        )
        assert any("効率" in v for v in violations)

    def test_opening_pattern_violation(self) -> None:
        """書き出しパターンが上限に達している場合に違反を検出する。"""
        text = "今日は、まるで嵐のような一日だった。段落。\n\nゆっくりと深呼吸をした。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=[],
            used_openings=["Day 1: 比喩型", "Day 2: 比喩型"],
            theme_word_totals={},
        )
        assert any("比喩型" in v for v in violations)

    def test_multiple_violations(self) -> None:
        """複数の違反が同時に検出される。"""
        text = "会議室で効率の話。効率化。効率的。効率主義。\n\nこれは何のだろうか......"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=["Day 1: 〜だろう系", "Day 2: 〜だろう系"],
            used_structures=["Day 1: 会議型"],
            used_openings=[],
            theme_word_totals={"効率": 10},
        )
        assert len(violations) >= 2

    def test_ending_pattern_strict_limit_early_days(self) -> None:
        """Day 1-5 では余韻パターンが1回で上限到達する。"""
        text = "段落1。\n\nこの本は何を知っているのだろう......"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=["Day 1: 〜だろう系"],
            used_structures=[],
            used_openings=[],
            theme_word_totals={},
            current_day=3,
        )
        assert any("〜だろう系" in v for v in violations)

    def test_ending_pattern_relaxed_limit_late_days(self) -> None:
        """Day 6-7 では余韻パターンが1回使用でも許容される。"""
        text = "段落1。\n\nこの本は何を知っているのだろう......"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=["Day 1: 〜だろう系"],
            used_structures=[],
            used_openings=[],
            theme_word_totals={},
            current_day=6,
        )
        assert not any("〜だろう系" in v for v in violations)

    def test_opening_pattern_strict_limit_early_days(self) -> None:
        """Day 1-5 では書き出しパターンが1回で上限到達する。"""
        text = "今日は、まるで嵐のような一日だった。段落。\n\nゆっくりと深呼吸をした。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=[],
            used_openings=["Day 1: 比喩型"],
            theme_word_totals={},
            current_day=4,
        )
        assert any("比喩型" in v for v in violations)

    def test_opening_pattern_relaxed_limit_late_days(self) -> None:
        """Day 6-7 では書き出しパターンが1回使用でも許容される。"""
        text = "今日は、まるで嵐のような一日だった。段落。\n\nゆっくりと深呼吸をした。"
        violations = _validate_structural_constraints(
            text,
            used_ending_patterns=[],
            used_structures=[],
            used_openings=["Day 1: 比喩型"],
            theme_word_totals={},
            current_day=7,
        )
        assert not any("比喩型" in v for v in violations)


class TestConstants:
    """共有定数の整合性テスト。"""

    def test_ending_pattern_examples_not_empty(self) -> None:
        """余韻パターン例が空でないこと。"""
        from csdg.engine.constants import ENDING_PATTERN_EXAMPLES

        assert len(ENDING_PATTERN_EXAMPLES) >= 7

    def test_opening_pattern_examples_not_empty(self) -> None:
        """書き出しパターン例が空でないこと。"""
        from csdg.engine.constants import OPENING_PATTERN_EXAMPLES

        assert len(OPENING_PATTERN_EXAMPLES) >= 6

    def test_theme_word_limits_ordering(self) -> None:
        """閾値の大小関係が正しいこと。"""
        from csdg.engine.constants import (
            THEME_WORD_HARD_LIMIT,
            THEME_WORD_PER_DAY_LIMIT,
            THEME_WORD_SOFT_LIMIT,
        )

        assert THEME_WORD_PER_DAY_LIMIT < THEME_WORD_SOFT_LIMIT < THEME_WORD_HARD_LIMIT

    def test_scene_marker_days_ordering(self) -> None:
        """シーンマーカー閾値の大小関係が正しいこと。"""
        from csdg.engine.constants import SCENE_MARKER_HARD_DAYS, SCENE_MARKER_SOFT_DAYS

        assert SCENE_MARKER_SOFT_DAYS < SCENE_MARKER_HARD_DAYS

    def test_no_circular_import(self) -> None:
        """actor.py が pipeline.py を直接インポートしていないこと。"""
        import ast
        import importlib.util
        from pathlib import Path

        spec = importlib.util.find_spec("csdg.engine.actor")
        assert spec is not None and spec.origin is not None
        actor_source = Path(spec.origin).read_text(encoding="utf-8")
        tree = ast.parse(actor_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "csdg.engine.pipeline" not in node.module, (
                    f"actor.py が pipeline.py を直接インポートしています (line {node.lineno})"
                )


# ====================================================================
# 冒頭テキスト抽出テスト (P0-1)
# ====================================================================


class TestExtractOpeningText:
    """_extract_opening_text のテスト。"""

    def test_skips_markdown_heading(self) -> None:
        """Markdown 見出し行をスキップする。"""
        text = "# タイトル\n\n本文の冒頭がここから始まる。"
        result = _extract_opening_text(text)
        assert result == "本文の冒頭がここから始まる。"

    def test_max_length(self) -> None:
        """80文字で切り詰められる。"""
        text = "あ" * 100
        result = _extract_opening_text(text)
        assert len(result) == 80

    def test_empty_text(self) -> None:
        """空テキストの場合は空文字列を返す。"""
        assert _extract_opening_text("") == ""
        assert _extract_opening_text("# 見出しのみ") == ""

    def test_skips_empty_lines(self) -> None:
        """空行をスキップする。"""
        text = "\n\n\n本文がここに。"
        assert _extract_opening_text(text) == "本文がここに。"


# ====================================================================
# 書き出しパターン分類改善テスト (P1-1)
# ====================================================================


class TestOpeningPatternImproved:
    """改善後の _detect_opening_pattern のテスト。"""

    def test_fragment_with_periods(self) -> None:
        """句点区切りの短フレーズが断片型に分類される。"""
        assert _detect_opening_pattern("会議。蛍光灯。スライド。沈黙。") == "断片型"

    def test_question_with_darou(self) -> None:
        """「だろう。」で終わる文が問い型に分類される。"""
        assert _detect_opening_pattern("効率って、いつから美徳になったんだろう。") == "問い型"

    def test_sensory_with_voice(self) -> None:
        """「声」を含む文が五感型に分類される。"""
        assert _detect_opening_pattern("古書店の奥で、ミナの声がまだ耳に残っている。") == "五感型"

    def test_darou_mid_sentence_not_question(self) -> None:
        """「だろう」が文中にあり末尾でない場合は問い型にならない。"""
        # "だろうと" のような継続形は末尾マッチしないので問い型にはならない
        result = _detect_opening_pattern("それは彼女だろうと思いながら歩いた長い帰り道の記憶が蘇る。")
        assert result != "問い型"


# ====================================================================
# 冒頭テキスト重複チェックテスト (P0-1)
# ====================================================================


class TestOpeningTextOverlapValidation:
    """_validate_structural_constraints の冒頭テキスト重複チェックのテスト。"""

    def test_detects_similar_opening(self) -> None:
        """類似した冒頭テキストが違反として検出される。"""
        diary = "問い型で始めよう——効率って、いつから美徳になったんだろう。" + "あ" * 1000
        prev_openings = ["問い型で始めよう——効率って、いつから美徳になったんだろう。"]
        violations = _validate_structural_constraints(
            diary,
            [],
            [],
            [],
            {},
            prev_openings_text=prev_openings,
        )
        assert any("冒頭テキスト" in v for v in violations)

    def test_different_openings_no_violation(self) -> None:
        """異なる冒頭テキストでは違反が発生しない。"""
        diary = "図書館のインクの匂いが、鼻の奥にまだ残っている。" + "あ" * 1000
        prev_openings = ["問い型で始めよう——効率って、いつから美徳になったんだろう。"]
        violations = _validate_structural_constraints(
            diary,
            [],
            [],
            [],
            {},
            prev_openings_text=prev_openings,
        )
        assert not any("冒頭テキスト" in v for v in violations)


# ====================================================================
# 余韻パターン分類改善テスト (P2-2)
# ====================================================================


class TestEndingPatternImproved:
    """改善後の _detect_ending_pattern のテスト。"""

    def test_two_sentence_action_ending(self) -> None:
        """末尾2文構成の行動締め系が正しく分類される。"""
        text = "本文がここにある。\n\nノートを閉じた。電気を消した。"
        assert _detect_ending_pattern(text) == "行動締め系"

    def test_taigen_dome_40chars(self) -> None:
        """40文字以下の漢字/カタカナ終わりが体言止め系に分類される。"""
        # 38文字の体言止め (旧30文字制限ではその他になっていたケース)
        text = "本文がここにある。\n\nそれは遠い記憶の中に沈んでいく、静かな残照"
        assert _detect_ending_pattern(text) == "体言止め系"

    def test_teiru_in_penultimate_sentence(self) -> None:
        """末尾から2文目が「〜ている」で終わる場合も〜ている系に分類される。"""
        text = "本文。\n\n蛍光灯の光が反射している。その光は一定ではない。"
        assert _detect_ending_pattern(text) == "〜ている系"


# ====================================================================
# 余韻テキスト重複チェックテスト (修正 B)
# ====================================================================


class TestEndingTextOverlapValidation:
    """_validate_structural_constraints の余韻テキスト重複チェックのテスト。"""

    def test_detects_similar_ending(self) -> None:
        """類似した余韻テキストが違反として検出される。"""
        diary = "冒頭文が十分に長いテストテキスト。\n\n缶コーヒーを飲み干して底に残った最後の一滴が落ちていく。"
        prev_endings = ["缶コーヒーを飲み干してゴミ箱に捨てた。底に残った最後の一滴が落ちていく。"]
        violations = _validate_structural_constraints(
            diary,
            [],
            [],
            [],
            {},
            prev_endings_text=prev_endings,
        )
        assert any("余韻テキスト" in v for v in violations)

    def test_different_endings_no_violation(self) -> None:
        """異なる余韻テキストでは違反が発生しない。"""
        diary = "冒頭文が十分に長いテストテキスト。\n\n窓の外に落ちる、最後の残照。"
        prev_endings = ["缶コーヒーを飲み干して底に残った最後の一滴が落ちていく。"]
        violations = _validate_structural_constraints(
            diary,
            [],
            [],
            [],
            {},
            prev_endings_text=prev_endings,
        )
        assert not any("余韻テキスト" in v for v in violations)


# --- 末尾フックの弱さ検出 (項目11) ---


class TestWeakHookDetection:
    """_validate_structural_constraints の末尾フック弱さ検出テスト。"""

    def test_weak_rhetorical_hook_detected(self) -> None:
        """弱い修辞疑問で閉じる日記が構造的違反として検出される。"""
        diary = "# テスト\n\nテスト本文。この金文字は、何年分の重みを覚えているのだろう......"
        violations = _validate_structural_constraints(
            diary, [], [], [], {}, current_day=2,
        )
        assert any("修辞疑問" in v for v in violations)

    def test_strong_rhetorical_hook_allowed(self) -> None:
        """具体的な人物に紐づく疑問はフックとして許可される。"""
        diary = "# テスト\n\nテスト本文。あの時の那由他さんの沈黙は何だったのだろう。"
        violations = _validate_structural_constraints(
            diary, [], [], [], {}, current_day=2,
        )
        assert not any("修辞疑問" in v for v in violations)

    def test_emotional_conclusion_hook_detected(self) -> None:
        """感情の結論で閉じる日記が構造的違反として検出される。"""
        diary = "# テスト\n\nテスト本文。そのことが、なぜか心地よい。"
        violations = _validate_structural_constraints(
            diary, [], [], [], {}, current_day=6,
        )
        assert any("感情の結論" in v for v in violations)

    def test_hook_check_skipped_day7(self) -> None:
        """Day 7 ではフック弱さチェックがスキップされる。"""
        diary = "# テスト\n\nテスト本文。そのことが、なぜか心地よい。"
        violations = _validate_structural_constraints(
            diary, [], [], [], {}, current_day=7,
        )
        assert not any("感情の結論" in v for v in violations)
