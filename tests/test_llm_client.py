"""csdg/engine/llm_client.py のテスト。

LLMClient 抽象クラスの定義確認と AnthropicClient のインスタンス化・
モックによる API 呼び出しパターンの検証。
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock
from pydantic import BaseModel

from csdg.engine.llm_client import AnthropicClient, LLMClient


class _SampleModel(BaseModel):
    """テスト用の Pydantic モデル。"""

    name: str
    value: int


@dataclass
class _MockUsage:
    """テスト用の Usage モック。"""

    input_tokens: int
    output_tokens: int


@dataclass
class _MockResponse:
    """テスト用の Response モック。"""

    content: list[TextBlock | ToolUseBlock]
    usage: _MockUsage


class TestLLMClientAbstract:
    """LLMClient 抽象クラスのテスト。"""

    def test_is_abstract(self) -> None:
        """LLMClient は直接インスタンス化できない。"""
        with pytest.raises(TypeError):
            LLMClient()  # type: ignore[abstract]

    def test_has_generate_structured_method(self) -> None:
        """LLMClient に generate_structured メソッドが定義されている。"""
        assert hasattr(LLMClient, "generate_structured")

    def test_has_generate_text_method(self) -> None:
        """LLMClient に generate_text メソッドが定義されている。"""
        assert hasattr(LLMClient, "generate_text")


class TestAnthropicClientInit:
    """AnthropicClient の初期化テスト。"""

    def test_instantiation(self) -> None:
        """AnthropicClient が正常にインスタンス化できる。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
        )
        assert isinstance(client, LLMClient)

    def test_is_subclass_of_llm_client(self) -> None:
        """AnthropicClient は LLMClient のサブクラスである。"""
        assert issubclass(AnthropicClient, LLMClient)

    def test_custom_model(self) -> None:
        """カスタムモデル名でインスタンス化できる。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-opus-4-20250514",
            base_url="https://api.anthropic.com",
        )
        assert client._model == "claude-opus-4-20250514"


class TestGenerateStructured:
    """generate_structured のテスト (モック使用)。"""

    @pytest.mark.asyncio()
    async def test_tool_use_pattern_constructs_correctly(self) -> None:
        """tool_use パターンで tools と tool_choice が正しく構築される。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
        )

        tool_use_block = ToolUseBlock(
            type="tool_use",
            id="toolu_test",
            name="structured_output",
            input={"name": "test", "value": 42},
        )
        mock_response = _MockResponse(
            content=[tool_use_block],
            usage=_MockUsage(input_tokens=100, output_tokens=50),
        )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            result = await client.generate_structured(
                system_prompt="You are a test.",
                user_prompt="Return structured data.",
                response_model=_SampleModel,
                temperature=0.7,
            )

            assert isinstance(result, _SampleModel)
            assert result.name == "test"
            assert result.value == 42

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["system"] == "You are a test."
            assert call_kwargs["messages"] == [{"role": "user", "content": "Return structured data."}]
            assert len(call_kwargs["tools"]) == 1
            assert call_kwargs["tools"][0]["name"] == "structured_output"
            assert call_kwargs["tool_choice"] == {"type": "tool", "name": "structured_output"}

    @pytest.mark.asyncio()
    async def test_tool_use_block_not_found_raises_value_error(self) -> None:
        """tool_use ブロックが見つからない場合に ValueError が発生する。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
        )

        text_block = TextBlock(type="text", text="some text")
        mock_response = _MockResponse(
            content=[text_block],
            usage=_MockUsage(input_tokens=100, output_tokens=50),
        )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            with pytest.raises(ValueError, match="tool_use ブロックが見つかりません"):
                await client.generate_structured(
                    system_prompt="test",
                    user_prompt="test",
                    response_model=_SampleModel,
                    temperature=0.7,
                )


class TestGenerateText:
    """generate_text のテスト (モック使用)。"""

    @pytest.mark.asyncio()
    async def test_system_prompt_passed_as_system_parameter(self) -> None:
        """system_prompt が messages ではなく system パラメータに渡される。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
        )

        text_block = TextBlock(type="text", text="Generated diary text.")
        mock_response = _MockResponse(
            content=[text_block],
            usage=_MockUsage(input_tokens=100, output_tokens=50),
        )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            result = await client.generate_text(
                system_prompt="You are Tokomi.",
                user_prompt="Write a diary.",
                temperature=0.7,
            )

            assert result == "Generated diary text."

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["system"] == "You are Tokomi."
            assert call_kwargs["messages"] == [{"role": "user", "content": "Write a diary."}]
            for msg in call_kwargs["messages"]:
                assert msg["role"] != "system"

    @pytest.mark.asyncio()
    async def test_empty_response_raises_value_error(self) -> None:
        """空文字列が返された場合に ValueError が発生する。"""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com",
        )

        text_block = TextBlock(type="text", text="")
        mock_response = _MockResponse(
            content=[text_block],
            usage=_MockUsage(input_tokens=100, output_tokens=0),
        )

        with patch.object(client._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            with pytest.raises(ValueError, match="LLM がテキストを返しませんでした"):
                await client.generate_text(
                    system_prompt="test",
                    user_prompt="test",
                    temperature=0.7,
                )
