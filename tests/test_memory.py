"""csdg/engine/memory.py のテスト.

MemoryManager の2層メモリ構造 (ShortTermMemory + LongTermMemory) を検証する.
"""

from __future__ import annotations

import pytest

from csdg.engine.memory import MemoryManager
from csdg.schemas import LongTermMemory, Memory, ShortTermMemory, TurningPoint


# ====================================================================
# フィクスチャ
# ====================================================================


@pytest.fixture()
def manager() -> MemoryManager:
    """デフォルト設定の MemoryManager."""
    return MemoryManager(window_size=3)


@pytest.fixture()
def manager_with_data() -> MemoryManager:
    """既存データを持つ MemoryManager."""
    memory = Memory(
        short_term=ShortTermMemory(
            window_size=3,
            entries=["[Day 1] entry1...", "[Day 2] entry2...", "[Day 3] entry3..."],
        ),
        long_term=LongTermMemory(
            beliefs=["効率は必ずしも善ではない"],
            recurring_themes=["都市と自然の対比"],
            turning_points=[TurningPoint(day=2, summary="大きな気づきがあった日")],
        ),
    )
    return MemoryManager(window_size=3, memory=memory)


# ====================================================================
# 短期記憶テスト
# ====================================================================


class TestShortTermMemory:
    """短期記憶の管理テスト."""

    def test_add_entry_within_window(self, manager: MemoryManager) -> None:
        """ウィンドウ内では全エントリが保持される."""
        manager.update_short_term("日記1", day=1)
        manager.update_short_term("日記2", day=2)

        assert len(manager.memory.short_term.entries) == 2
        assert "[Day 1]" in manager.memory.short_term.entries[0]
        assert "[Day 2]" in manager.memory.short_term.entries[1]

    def test_sliding_window_eviction(self, manager: MemoryManager) -> None:
        """ウィンドウサイズ超過時に古いエントリが押し出される."""
        for day in range(1, 5):
            manager.update_short_term(f"Day {day} の日記", day=day)

        entries = manager.memory.short_term.entries
        assert len(entries) == 3
        assert "[Day 2]" in entries[0]
        assert "[Day 3]" in entries[1]
        assert "[Day 4]" in entries[2]

    def test_eviction_returns_evicted_entries(self, manager: MemoryManager) -> None:
        """update_short_term が押し出されたエントリを返す."""
        for day in range(1, 4):
            evicted = manager.update_short_term(f"Day {day} の日記", day=day)
            assert evicted == []

        evicted = manager.update_short_term("Day 4 の日記", day=4)
        assert len(evicted) == 1
        assert "[Day 1]" in evicted[0]

    def test_summary_truncation(self, manager: MemoryManager) -> None:
        """日記テキストが100文字で切り詰められる."""
        long_text = "あ" * 200
        manager.update_short_term(long_text, day=1)

        entry = manager.memory.short_term.entries[0]
        assert entry.startswith("[Day 1] ")
        assert entry.endswith("...")
        assert len(entry) < 200


# ====================================================================
# 長期記憶テスト
# ====================================================================


class TestLongTermMemory:
    """長期記憶の管理テスト."""

    def test_add_belief_no_duplicate(self, manager: MemoryManager) -> None:
        """beliefs が重複追加されない."""
        manager.add_belief("効率は善ではない")
        manager.add_belief("効率は善ではない")

        assert len(manager.memory.long_term.beliefs) == 1

    def test_add_multiple_beliefs(self, manager: MemoryManager) -> None:
        """異なる信念が追加される."""
        manager.add_belief("信念A")
        manager.add_belief("信念B")

        assert len(manager.memory.long_term.beliefs) == 2

    def test_add_theme_no_duplicate(self, manager: MemoryManager) -> None:
        """recurring_themes が重複追加されない."""
        manager.add_theme("テーマA")
        manager.add_theme("テーマA")

        assert len(manager.memory.long_term.recurring_themes) == 1

    def test_beliefs_compaction(self, manager: MemoryManager) -> None:
        """beliefs が上限 (10) を超えた場合に古いものが削除される."""
        for i in range(15):
            manager.add_belief(f"信念{i}")

        manager._compact_long_term()
        assert len(manager.memory.long_term.beliefs) <= 10

    def test_themes_compaction(self, manager: MemoryManager) -> None:
        """recurring_themes が上限 (5) を超えた場合に古いものが削除される."""
        for i in range(8):
            manager.add_theme(f"テーマ{i}")

        manager._compact_long_term()
        assert len(manager.memory.long_term.recurring_themes) <= 5


# ====================================================================
# update_after_day テスト
# ====================================================================


class TestUpdateAfterDay:
    """update_after_day の統合テスト."""

    @pytest.mark.asyncio()
    async def test_basic_update(self, manager: MemoryManager) -> None:
        """基本的な Day 更新."""
        await manager.update_after_day("今日の日記テキスト", day=1)

        assert len(manager.memory.short_term.entries) == 1
        assert "[Day 1]" in manager.memory.short_term.entries[0]

    @pytest.mark.asyncio()
    async def test_eviction_triggers_long_term_extraction(self, manager: MemoryManager) -> None:
        """ウィンドウ超過時に long_term への抽出が行われる (転機キーワード)."""
        # Day 1-3 を追加
        await manager.update_after_day("通常の日記", day=1)
        await manager.update_after_day("転機となる大きな気づきがあった", day=2)
        await manager.update_after_day("通常の日記3", day=3)

        # Day 4 で Day 1 が evict される (転機キーワードなし → turning_points 増えない)
        await manager.update_after_day("通常の日記4", day=4)

        # Day 5 で Day 2 ("転機") が evict される
        await manager.update_after_day("通常の日記5", day=5)

        assert len(manager.memory.long_term.turning_points) >= 1

    @pytest.mark.asyncio()
    async def test_10_day_simulation(self, manager: MemoryManager) -> None:
        """10Day 以上のシミュレーションでメモリが正常に機能する."""
        for day in range(1, 11):
            await manager.update_after_day(f"Day {day} の日記: 哲学的考察と日常の記録", day=day)

        # short_term は直近3日分のみ
        assert len(manager.memory.short_term.entries) == 3
        assert "[Day 8]" in manager.memory.short_term.entries[0]
        assert "[Day 9]" in manager.memory.short_term.entries[1]
        assert "[Day 10]" in manager.memory.short_term.entries[2]


# ====================================================================
# get_context テスト
# ====================================================================


class TestGetContext:
    """コンテキスト取得のテスト."""

    def test_get_context_for_actor_contains_both(self, manager_with_data: MemoryManager) -> None:
        """get_context_for_actor が short_term と long_term の両方を含む."""
        ctx = manager_with_data.get_context_for_actor()

        assert "short_term_entries" in ctx
        assert "beliefs" in ctx
        assert "recurring_themes" in ctx
        assert "turning_points" in ctx

        assert len(ctx["short_term_entries"]) == 3  # type: ignore[arg-type]
        assert len(ctx["beliefs"]) == 1  # type: ignore[arg-type]

    def test_get_context_for_critic(self, manager_with_data: MemoryManager) -> None:
        """get_context_for_critic が long_term 情報を含む."""
        ctx = manager_with_data.get_context_for_critic()

        assert "beliefs" in ctx
        assert "recurring_themes" in ctx
        assert ctx["beliefs"] == ["効率は必ずしも善ではない"]

    def test_empty_manager_returns_empty_context(self, manager: MemoryManager) -> None:
        """空の MemoryManager でも正常にコンテキストを返す."""
        ctx = manager.get_context_for_actor()

        assert ctx["short_term_entries"] == []
        assert ctx["beliefs"] == []
        assert ctx["recurring_themes"] == []
        assert ctx["turning_points"] == []


# ====================================================================
# get_memory_buffer_for_state テスト
# ====================================================================


class TestMemoryBufferForState:
    """CharacterState 後方互換性テスト."""

    def test_returns_short_term_entries(self, manager_with_data: MemoryManager) -> None:
        """get_memory_buffer_for_state が short_term.entries を返す."""
        buffer = manager_with_data.get_memory_buffer_for_state()

        assert len(buffer) == 3
        assert "[Day 1]" in buffer[0]

    def test_returns_copy(self, manager_with_data: MemoryManager) -> None:
        """返却値の変更がメモリに影響しない."""
        buffer = manager_with_data.get_memory_buffer_for_state()
        buffer.append("extra")

        assert len(manager_with_data.memory.short_term.entries) == 3


# ====================================================================
# ヘルパーメソッドテスト
# ====================================================================


class TestHelpers:
    """ヘルパーメソッドのテスト."""

    def test_extract_day_from_entry(self) -> None:
        """Day 番号の抽出."""
        assert MemoryManager._extract_day_from_entry("[Day 5] some text...") == 5
        assert MemoryManager._extract_day_from_entry("[Day 12] some text...") == 12
        assert MemoryManager._extract_day_from_entry("no day marker") == 0

    def test_has_duplicate_turning_point(self, manager_with_data: MemoryManager) -> None:
        """既存の転換点 Day の重複チェック."""
        assert manager_with_data._has_duplicate_turning_point(2) is True
        assert manager_with_data._has_duplicate_turning_point(5) is False
