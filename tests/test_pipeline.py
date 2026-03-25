"""csdg/engine/pipeline.py のテスト。

正常系、リトライ、Temperature Decay、Best-of-N、Phase 1 フォールバック、
メモリ管理、Dayスキップ、パイプライン中断の各パターンをモックで検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from csdg.config import CSDGConfig
from csdg.engine.actor import Actor
from csdg.engine.critic import Critic, judge
from csdg.engine.pipeline import PipelineRunner, RetryCandidate
from csdg.schemas import CharacterState, CriticResult, CriticScore, DailyEvent, LayerScore

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
        mock_actor.update_state.return_value = updated_state
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
        mock_actor.update_state.return_value = updated_state
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
        mock_actor.update_state.return_value = updated_state
        mock_actor.generate_diary.return_value = "今日の日記です。" * 10

        # 3回 Reject → Best-of-N
        reject1 = _make_reject_score(temporal=2)
        reject2 = _make_reject_score(temporal=2, emotional=3)
        reject3 = _make_reject_score(temporal=2, emotional=2)
        mock_critic.evaluate_full.side_effect = [_wrap_as_result(reject1), _wrap_as_result(reject2), _wrap_as_result(reject3)]

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
        mock_actor.update_state.return_value = updated_state

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
        mock_critic.evaluate_full.side_effect = [_wrap_as_result(reject1), _wrap_as_result(reject2), _wrap_as_result(reject3)]

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
        ) -> CharacterState:
            return prev.model_copy(update={"stress": 0.0})

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

    def test_update_memory_buffer_sliding_window(
        self,
        runner: PipelineRunner,
        state: CharacterState,
    ) -> None:
        """_update_memory_buffer が window size を維持すること。"""
        # Day 1〜4 まで buffer に追加
        current = state
        for day in range(1, 5):
            current = runner._update_memory_buffer(current, f"Day {day} の日記テキスト", day)

        # window_size=3 なので Day2, Day3, Day4 の要約のみ残る
        assert len(current.memory_buffer) == 3
        assert "[Day 2]" in current.memory_buffer[0]
        assert "[Day 3]" in current.memory_buffer[1]
        assert "[Day 4]" in current.memory_buffer[2]

    def test_update_memory_buffer_at_day5(
        self,
        runner: PipelineRunner,
        state: CharacterState,
    ) -> None:
        """Day 5 で buffer が [Day3, Day4, Day5] になること。"""
        current = state
        for day in range(1, 6):
            current = runner._update_memory_buffer(current, f"Day {day} の日記テキスト", day)

        assert len(current.memory_buffer) == 3
        assert "[Day 3]" in current.memory_buffer[0]
        assert "[Day 4]" in current.memory_buffer[1]
        assert "[Day 5]" in current.memory_buffer[2]


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
        ) -> CharacterState:
            nonlocal call_count
            call_count += 1
            if event.day == 3:
                raise RuntimeError("予期しないエラー")
            return updated_state

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
        ) -> CharacterState:
            if event.day >= 3:
                raise RuntimeError("連続失敗シミュレーション")
            return updated_state

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
