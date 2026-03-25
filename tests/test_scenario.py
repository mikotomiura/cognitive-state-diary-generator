"""csdg/scenario.py のテスト。

SCENARIO, INITIAL_STATE, validate_scenario() の正常系・異常系テストを網羅する。
test-standards/SKILL.md の AAA パターンおよび命名規約に従う。
"""

from __future__ import annotations

import pytest

from csdg.scenario import INITIAL_STATE, SCENARIO, validate_scenario
from csdg.schemas import DailyEvent


class TestScenarioDefinition:
    """SCENARIO リストの定義テスト。"""

    def test_scenario_count(self) -> None:
        """SCENARIO は7件のイベントを含む。"""
        assert len(SCENARIO) == 7

    def test_days_are_sequential(self) -> None:
        """day が 1〜7 の連番である。"""
        days = [event.day for event in SCENARIO]
        assert days == [1, 2, 3, 4, 5, 6, 7]

    @pytest.mark.parametrize("index", range(7))
    def test_all_event_types_valid(self, index: int) -> None:
        """全イベントの event_type が有効な値である。"""
        event = SCENARIO[index]
        assert event.event_type in {"positive", "negative", "neutral"}

    @pytest.mark.parametrize("index", range(7))
    def test_emotional_impact_in_range(self, index: int) -> None:
        """全イベントの emotional_impact が -1.0〜1.0 の範囲内である。"""
        event = SCENARIO[index]
        assert -1.0 <= event.emotional_impact <= 1.0

    def test_day4_emotional_impact(self) -> None:
        """Day 4 の emotional_impact が -0.9 である（ストレステスト確認）。"""
        day4 = SCENARIO[3]
        assert day4.day == 4
        assert day4.emotional_impact == -0.9

    @pytest.mark.parametrize("index", range(7))
    def test_description_min_length(self, index: int) -> None:
        """全イベントの description が10文字以上である。"""
        event = SCENARIO[index]
        assert len(event.description) >= 10


class TestInitialState:
    """INITIAL_STATE の初期値テスト。"""

    def test_fatigue(self) -> None:
        """fatigue の初期値が 0.1 である。"""
        assert INITIAL_STATE.fatigue == 0.1

    def test_motivation(self) -> None:
        """motivation の初期値が 0.2 である。"""
        assert INITIAL_STATE.motivation == 0.2

    def test_stress(self) -> None:
        """stress の初期値が -0.1 である。"""
        assert INITIAL_STATE.stress == -0.1

    def test_current_focus(self) -> None:
        """current_focus の初期値が正しい。"""
        assert INITIAL_STATE.current_focus == "来週の社内コードレビュー会の準備"

    def test_unresolved_issue(self) -> None:
        """unresolved_issue の初期値が None である。"""
        assert INITIAL_STATE.unresolved_issue is None

    def test_growth_theme(self) -> None:
        """growth_theme の初期値が正しい。"""
        assert INITIAL_STATE.growth_theme == "「考えること」と「生きること」の折り合い"

    def test_memory_buffer(self) -> None:
        """memory_buffer の初期値が空リストである。"""
        assert INITIAL_STATE.memory_buffer == []

    def test_relationships(self) -> None:
        """relationships の初期値が正しい。"""
        assert INITIAL_STATE.relationships == {"深森那由他": 0.6, "ミナ": 0.4}


class TestValidateScenario:
    """validate_scenario() のテスト。"""

    def test_valid_scenario_no_exception(self) -> None:
        """正常なシナリオではバリデーションが例外を出さない。"""
        validate_scenario(SCENARIO)

    def test_empty_list_raises(self) -> None:
        """空リストで ValueError が発生する。"""
        with pytest.raises(ValueError, match="空です"):
            validate_scenario([])

    def test_missing_day_raises(self) -> None:
        """day に欠番がある場合 ValueError が発生する。"""
        events = [
            DailyEvent(
                day=1,
                event_type="neutral",
                domain="仕事",
                emotional_impact=0.2,
                description="テスト用のイベント記述です",
            ),
            DailyEvent(
                day=3,
                event_type="positive",
                domain="趣味",
                emotional_impact=0.5,
                description="テスト用のイベント記述です",
            ),
        ]
        with pytest.raises(ValueError, match="連番"):
            validate_scenario(events)

    def test_day_not_starting_from_one_raises(self) -> None:
        """day が 1 から始まらない場合 ValueError が発生する。"""
        events = [
            DailyEvent(
                day=2,
                event_type="neutral",
                domain="仕事",
                emotional_impact=0.2,
                description="テスト用のイベント記述です",
            ),
        ]
        with pytest.raises(ValueError, match="連番"):
            validate_scenario(events)

    def test_single_valid_event(self) -> None:
        """1件の正常なイベントではバリデーションが通る。"""
        events = [
            DailyEvent(
                day=1,
                event_type="neutral",
                domain="仕事",
                emotional_impact=0.2,
                description="テスト用のイベント記述です",
            ),
        ]
        validate_scenario(events)
