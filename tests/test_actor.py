"""csdg/engine/actor.py のテスト。

LLMClient をモックし、Actor の update_state / generate_diary の
正常系・異常系を検証する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from csdg.engine.actor import Actor
from csdg.schemas import CharacterState, DailyEvent

if TYPE_CHECKING:
    from pathlib import Path

    from csdg.config import CSDGConfig
    from csdg.engine.llm_client import LLMClient


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    """テスト用プロンプトディレクトリを作成する。"""
    persona = tmp_path / "System_Persona.md"
    persona.write_text("You are Tokomi.", encoding="utf-8")

    state_update = tmp_path / "Prompt_StateUpdate.md"
    state_update.write_text(
        "Update state.\nprevious_state: {previous_state}\nevent: {event}\nmemory: {memory_buffer}",
        encoding="utf-8",
    )

    generator = tmp_path / "Prompt_Generator.md"
    generator.write_text(
        "Write diary.\n"
        "state: {current_state}\n"
        "event: {event}\n"
        "memory: {memory_buffer}\n"
        "{revision_instruction}\n"
        "{prev_endings}",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture()
def actor(
    mock_llm_client: LLMClient,
    test_config: CSDGConfig,
    prompts_dir: Path,
) -> Actor:
    """テスト用 Actor インスタンス。"""
    return Actor(mock_llm_client, test_config, prompts_dir=prompts_dir)


class TestUpdateState:
    """Actor.update_state のテスト。"""

    @pytest.mark.asyncio()
    async def test_returns_character_state(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """update_state が CharacterState を返す。

        半数式化により、LLM 出力の連続変数は compute_next_state で
        再計算されるため、LLM mock の値と完全一致しない。
        離散変数は LLM 出力がそのまま採用される。
        """
        llm_output = initial_state.model_copy(
            update={"stress": 0.1, "motivation": 0.3, "current_focus": "新しい関心事"},
        )
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = llm_output

        result, delta_reason = await actor.update_state(initial_state, sample_event)

        assert isinstance(result, CharacterState)
        assert isinstance(delta_reason, str)
        assert len(delta_reason) > 0
        # 連続変数は数式で統合されるため、範囲内にあることを確認
        assert -1.0 <= result.stress <= 1.0
        assert -1.0 <= result.motivation <= 1.0
        assert -1.0 <= result.fatigue <= 1.0
        # 離散変数は LLM 出力がそのまま採用
        assert result.current_focus == "新しい関心事"

    @pytest.mark.asyncio()
    async def test_calls_generate_structured(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """update_state が LLMClient.generate_structured を呼び出す。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = initial_state

        await actor.update_state(initial_state, sample_event)

        mock_llm_client.generate_structured.assert_called_once()
        call_kwargs = mock_llm_client.generate_structured.call_args
        assert call_kwargs.kwargs["response_model"] is CharacterState
        assert call_kwargs.kwargs["system_prompt"] == "You are Tokomi."

    @pytest.mark.asyncio()
    async def test_prompt_contains_previous_state(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """User Prompt に前日の状態の JSON が含まれている。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = initial_state

        await actor.update_state(initial_state, sample_event)

        user_prompt = mock_llm_client.generate_structured.call_args.kwargs["user_prompt"]
        assert '"fatigue"' in user_prompt
        assert '"motivation"' in user_prompt

    @pytest.mark.asyncio()
    async def test_empty_memory_buffer_shows_placeholder(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """memory_buffer が空の場合、"(記憶なし)" がプロンプトに含まれる。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = initial_state

        await actor.update_state(initial_state, sample_event)

        user_prompt = mock_llm_client.generate_structured.call_args.kwargs["user_prompt"]
        assert "(記憶なし)" in user_prompt

    @pytest.mark.asyncio()
    async def test_nonempty_memory_buffer_in_prompt(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        sample_event: DailyEvent,
    ) -> None:
        """memory_buffer に内容がある場合、プロンプトに含まれる。"""
        state_with_memory = CharacterState(
            fatigue=0.1,
            motivation=0.2,
            stress=-0.1,
            current_focus="テスト",
            growth_theme="テーマ",
            memory_buffer=["Day 1の記憶", "Day 2の記憶"],
            relationships={"深森那由他": 0.6, "ミナ": 0.4},
        )
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = state_with_memory

        await actor.update_state(state_with_memory, sample_event)

        user_prompt = mock_llm_client.generate_structured.call_args.kwargs["user_prompt"]
        assert "Day 1の記憶" in user_prompt
        assert "Day 2の記憶" in user_prompt
        assert "(記憶なし)" not in user_prompt


class TestDeltaReason:
    """Actor._generate_delta_reason のテスト。"""

    @pytest.mark.asyncio()
    async def test_update_state_returns_tuple(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """update_state が (CharacterState, str) のタプルを返す。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_structured.return_value = initial_state

        result = await actor.update_state(initial_state, sample_event)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], CharacterState)
        assert isinstance(result[1], str)
        assert len(result[1]) > 0

    @pytest.mark.asyncio()
    async def test_delta_reason_contains_event_info(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """delta_reason にイベント情報とパラメータ名が含まれる。"""
        assert isinstance(mock_llm_client, AsyncMock)
        llm_output = initial_state.model_copy(
            update={"stress": 0.5, "motivation": 0.3},
        )
        mock_llm_client.generate_structured.return_value = llm_output

        _, delta_reason = await actor.update_state(initial_state, sample_event)

        # イベント description の一部が含まれる
        assert "自動化スクリプト" in delta_reason
        # パラメータ名が含まれる
        assert any(p in delta_reason for p in ("fatigue", "motivation", "stress"))


class TestGenerateDiary:
    """Actor.generate_diary のテスト。"""

    @pytest.mark.asyncio()
    async def test_returns_string(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """generate_diary が文字列を返す。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "今日の日記テキスト"

        result = await actor.generate_diary(initial_state, sample_event)

        assert isinstance(result, str)
        assert result == "今日の日記テキスト"

    @pytest.mark.asyncio()
    async def test_calls_generate_text(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """generate_diary が LLMClient.generate_text を呼び出す。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "日記テキスト"

        await actor.generate_diary(initial_state, sample_event)

        mock_llm_client.generate_text.assert_called_once()
        call_kwargs = mock_llm_client.generate_text.call_args
        assert call_kwargs.kwargs["system_prompt"] == "You are Tokomi."

    @pytest.mark.asyncio()
    async def test_no_revision_instruction(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """revision_instruction が None の場合、修正指示セクションが含まれない。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "日記テキスト"

        await actor.generate_diary(initial_state, sample_event, revision_instruction=None)

        user_prompt = mock_llm_client.generate_text.call_args.kwargs["user_prompt"]
        assert "## 修正指示" not in user_prompt

    @pytest.mark.asyncio()
    async def test_with_revision_instruction(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
        initial_state: CharacterState,
        sample_event: DailyEvent,
    ) -> None:
        """revision_instruction が文字列の場合、修正指示セクションが含まれる。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "日記テキスト"

        await actor.generate_diary(
            initial_state,
            sample_event,
            revision_instruction="絵文字を削除してください",
        )

        user_prompt = mock_llm_client.generate_text.call_args.kwargs["user_prompt"]
        assert "## 修正指示" in user_prompt
        assert "絵文字を削除してください" in user_prompt


class TestPromptLoading:
    """プロンプトファイルの読み込みテスト。"""

    def test_missing_prompt_raises_file_not_found(
        self,
        tmp_path: Path,
    ) -> None:
        """存在しないプロンプトファイルを指定すると FileNotFoundError。"""
        from csdg.engine.prompt_loader import load_prompt

        with pytest.raises(FileNotFoundError, match="プロンプトファイルが見つかりません"):
            load_prompt(tmp_path, "NonExistent.md")

    def test_load_prompt_returns_content(
        self,
        prompts_dir: Path,
    ) -> None:
        """load_prompt が正しいファイル内容を返す。"""
        from csdg.engine.prompt_loader import load_prompt

        content = load_prompt(prompts_dir, "System_Persona.md")
        assert content == "You are Tokomi."


# ====================================================================
# _format_long_term_context のテスト (#21)
# ====================================================================


class TestFormatLongTermContext:
    """Actor._format_long_term_context のテスト。"""

    def test_all_fields_present(self) -> None:
        ctx = {
            "beliefs": ["信念A"],
            "recurring_themes": ["テーマA"],
            "turning_points": [{"day": 2, "summary": "転換点"}],
        }
        result = Actor._format_long_term_context(ctx)
        assert "とこみの信念" in result
        assert "- 信念A" in result
        assert "Day 2: 転換点" in result

    def test_empty_context_returns_empty_string(self) -> None:
        result = Actor._format_long_term_context({"beliefs": [], "recurring_themes": [], "turning_points": []})
        assert result == ""

    def test_partial_context_only_beliefs(self) -> None:
        result = Actor._format_long_term_context({"beliefs": ["信念A"], "recurring_themes": [], "turning_points": []})
        assert "とこみの信念" in result
        assert "繰り返し現れるテーマ" not in result


# ====================================================================
# prev_endings のプロンプト注入テスト
# ====================================================================


class TestPrevEndings:
    """prev_endings のプロンプト注入テスト。"""

    @pytest.mark.asyncio()
    async def test_prev_endings_injected_into_prompt(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
    ) -> None:
        """prev_endings が渡された場合、プロンプトに余韻セクションが含まれる。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "日記テキスト"

        from csdg.schemas import DailyEvent

        event = DailyEvent(
            day=2,
            event_type="neutral",
            domain="仕事",
            description="テストイベントの説明文です",
            emotional_impact=0.2,
        )
        state = CharacterState(
            fatigue=0.1,
            motivation=0.2,
            stress=-0.1,
            current_focus="x",
            growth_theme="x",
        )

        await actor.generate_diary(state, event, prev_endings=["余韻A......。", "余韻B......。"])

        user_prompt = mock_llm_client.generate_text.call_args.kwargs["user_prompt"]
        assert "過去の余韻" in user_prompt
        assert "余韻A" in user_prompt
        assert "余韻B" in user_prompt

    @pytest.mark.asyncio()
    async def test_no_prev_endings_no_section(
        self,
        actor: Actor,
        mock_llm_client: LLMClient,
    ) -> None:
        """prev_endings が None の場合、余韻セクションが含まれない。"""
        assert isinstance(mock_llm_client, AsyncMock)
        mock_llm_client.generate_text.return_value = "日記テキスト"

        from csdg.schemas import DailyEvent

        event = DailyEvent(
            day=1,
            event_type="neutral",
            domain="仕事",
            description="テストイベントの説明文です",
            emotional_impact=0.2,
        )
        state = CharacterState(
            fatigue=0.1,
            motivation=0.2,
            stress=-0.1,
            current_focus="x",
            growth_theme="x",
        )

        await actor.generate_diary(state, event, prev_endings=None)

        user_prompt = mock_llm_client.generate_text.call_args.kwargs["user_prompt"]
        assert "過去の余韻" not in user_prompt
