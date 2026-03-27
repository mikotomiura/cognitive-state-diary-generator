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
    _detect_opening_pattern,
    _extract_ending,
    _extract_key_images,
    _sanitize_revision,
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
        llm_api_key="test-key",
        llm_model="gpt-4o",
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
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10
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
        # 最後に使用された temperature は schedule の最後
        schedule = config.temperature_schedule
        assert record.temperature_used == pytest.approx(schedule[-1])


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
            llm_api_key="test-key",
            llm_model="gpt-4o",
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

        call_count = 0

        async def generate_with_unique_ending(
            *args: object,
            **kwargs: object,
        ) -> str:
            nonlocal call_count
            call_count += 1
            return f"段落。\n\n余韻{call_count}......。"

        mock_actor.generate_diary.side_effect = generate_with_unique_ending
        mock_critic.evaluate_full.return_value = _wrap_as_result(_make_pass_score())

        events = _make_events(5)
        await runner.run(events, state)

        # Day 5 の呼び出しで prev_endings が3件に制限されている
        day5_call = mock_actor.generate_diary.call_args_list[4]
        prev_endings = day5_call.kwargs["prev_endings"]
        assert len(prev_endings) == 3
        assert "余韻2" in prev_endings[0]
        assert "余韻3" in prev_endings[1]
        assert "余韻4" in prev_endings[2]


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
