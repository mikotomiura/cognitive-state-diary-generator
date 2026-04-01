"""
LLM API 呼び出しの抽象インターフェースと Anthropic Claude 実装。

architecture.md §8.3 に基づき、LLM 呼び出しを抽象化する。
AnthropicClient は tool_use パターンで構造化出力を実現する。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar

from anthropic import AsyncAnthropic
from anthropic.types import TextBlock, ToolUseBlock
from pydantic import BaseModel

if TYPE_CHECKING:
    from anthropic.types.tool_param import ToolParam

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """LLM API 呼び出しの抽象インターフェース。

    Phase 1, 3 で使用する構造化生成 (Structured Outputs) と、
    Phase 2 で使用するプレーンテキスト生成の2つのメソッドを定義する。
    """

    @abstractmethod
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float,
    ) -> T:
        """Structured Outputs による構造化生成。

        Args:
            system_prompt: System Prompt テキスト (System_Persona.md)。
            user_prompt: User Prompt テキスト (Phase 固有プロンプト + 動的データ)。
            response_model: 出力の Pydantic モデルクラス。
            temperature: 生成時の Temperature パラメータ。

        Returns:
            response_model のインスタンス。

        Raises:
            pydantic.ValidationError: LLM 出力がスキーマに適合しない場合。
            anthropic.APIError: API 呼び出しに失敗した場合。
        """
        ...

    @abstractmethod
    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 4096,
    ) -> str:
        """プレーンテキスト生成。

        Args:
            system_prompt: System Prompt テキスト (System_Persona.md)。
            user_prompt: User Prompt テキスト (Prompt_Generator.md + 動的データ)。
            temperature: 生成時の Temperature パラメータ。
            max_tokens: 最大トークン数。

        Returns:
            生成されたテキスト。

        Raises:
            ValueError: 生成結果が空文字列の場合。
            anthropic.APIError: API 呼び出しに失敗した場合。
        """
        ...


class AnthropicClient(LLMClient):
    """Anthropic Claude API を使用した LLMClient 実装。

    AsyncAnthropic クライアントを内部で保持し、
    tool_use パターンによる構造化生成とプレーンテキスト生成を提供する。
    """

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        """AnthropicClient を初期化する。

        Args:
            api_key: Anthropic API キー。
            model: 使用する LLM モデル名 (例: "claude-sonnet-4-20250514")。
            base_url: API のベース URL。
        """
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=5)
        self._model = model
        logger.debug("AnthropicClient initialized: model=%s, base_url=%s", model, base_url)

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float,
    ) -> T:
        """tool_use パターンによる構造化生成。

        response_model の JSON Schema を tools パラメータに渡し、
        tool_choice で強制呼び出しすることで構造化出力を取得する。

        Args:
            system_prompt: System Prompt テキスト。
            user_prompt: User Prompt テキスト。
            response_model: 出力の Pydantic モデルクラス。
            temperature: 生成時の Temperature パラメータ。

        Returns:
            response_model のインスタンス。

        Raises:
            pydantic.ValidationError: LLM 出力がスキーマに適合しない場合。
            ValueError: tool_use ブロックが見つからない場合。
            anthropic.APIError: API 呼び出しに失敗した場合。
        """
        logger.debug(
            "generate_structured: model=%s, response_model=%s, temperature=%.2f",
            self._model,
            response_model.__name__,
            temperature,
        )

        tool_def: ToolParam = {
            "name": "structured_output",
            "description": "構造化データを出力するためのツール",
            "input_schema": response_model.model_json_schema(),
        }

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "structured_output"},
            temperature=temperature,
        )

        logger.debug(
            "generate_structured response: input_tokens=%d, output_tokens=%d",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # tool_use ブロックを探す
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                return response_model.model_validate(block.input)

        raise ValueError(
            f"tool_use ブロックが見つかりません (response content types: {[b.type for b in response.content]})"
        )

    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 4096,
    ) -> str:
        """プレーンテキスト生成。

        Anthropic API の system パラメータに system_prompt を渡し、
        messages に user_prompt を渡して自由テキストを生成する。

        Args:
            system_prompt: System Prompt テキスト。
            user_prompt: User Prompt テキスト。
            temperature: 生成時の Temperature パラメータ。
            max_tokens: 最大トークン数。

        Returns:
            生成されたテキスト。

        Raises:
            ValueError: 生成結果が空文字列の場合。
            anthropic.APIError: API 呼び出しに失敗した場合。
        """
        logger.debug(
            "generate_text: model=%s, temperature=%.2f, max_tokens=%d",
            self._model,
            temperature,
            max_tokens,
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
        )

        logger.debug(
            "generate_text response: input_tokens=%d, output_tokens=%d",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        first_block = response.content[0] if response.content else None
        content = first_block.text if isinstance(first_block, TextBlock) else ""
        if not content:
            raise ValueError("LLM がテキストを返しませんでした (空文字列)")

        return content
