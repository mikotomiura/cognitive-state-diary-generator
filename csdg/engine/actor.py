"""Actor モジュール -- Phase 1 (状態遷移) と Phase 2 (日記生成) を担当する。

architecture.md SS3.1, SS3.2, SS6 に準拠し、LLMClient を介して LLM を呼び出す。
プロンプトは prompts/ ディレクトリの外部 Markdown ファイルから読み込み、
プレースホルダをテンプレート展開して使用する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from csdg.engine.prompt_loader import load_prompt
from csdg.engine.state_transition import compute_next_state
from csdg.schemas import CharacterState, DailyEvent, EmotionalDelta

if TYPE_CHECKING:
    from csdg.config import CSDGConfig
    from csdg.engine.llm_client import LLMClient

logger = logging.getLogger(__name__)

_DEFAULT_PROMPTS_DIR = Path("prompts")


class Actor:
    """Phase 1 (状態遷移) と Phase 2 (日記生成) を担当する。

    LLMClient を介して LLM API を呼び出し、プロンプトファイルを
    テンプレート展開して各 Phase の処理を実行する。

    Attributes:
        _client: LLM API クライアント。
        _config: パイプライン設定。
        _prompts_dir: プロンプトファイルのディレクトリパス。
    """

    def __init__(
        self,
        client: LLMClient,
        config: CSDGConfig,
        prompts_dir: Path | None = None,
    ) -> None:
        """Actor を初期化する。

        Args:
            client: LLM API クライアント。
            config: パイプライン設定。
            prompts_dir: プロンプトファイルのディレクトリパス。
                None の場合はデフォルト (prompts/) を使用する。
        """
        self._client = client
        self._config = config
        self._prompts_dir = prompts_dir or _DEFAULT_PROMPTS_DIR

    async def update_state(
        self,
        prev_state: CharacterState,
        event: DailyEvent,
        long_term_context: dict[str, Any] | None = None,  # LongTermMemory の構造が可変のため Any を許容
    ) -> tuple[CharacterState, str]:
        """Phase 1: イベントに基づきキャラクターの内部状態を更新する。

        半数式化アプローチ:
        1. LLM に EmotionalDelta (補正値) を提案させる
        2. compute_next_state() で決定論的骨格 + LLM delta を統合
        3. LLM に離散変数 (current_focus 等) を更新させる

        Args:
            prev_state: 前日のキャラクター内部状態 (h_{t-1})。
            event: 当日のイベント定義 (x_t)。
            long_term_context: 長期記憶コンテキスト(信念・テーマ・転換点)。None の場合は注入しない。

        Returns:
            (更新されたキャラクター内部状態 (h_t), delta の変化理由) のタプル。

        Raises:
            pydantic.ValidationError: LLM 出力がスキーマに適合しない場合。
            FileNotFoundError: プロンプトファイルが見つからない場合。
        """
        system_prompt = load_prompt(self._prompts_dir, "System_Persona.md")
        user_prompt = self._build_state_update_prompt(prev_state, event, long_term_context)

        logger.debug(
            "Phase 1: update_state called (day=%d, emotional_impact=%.2f)",
            event.day,
            event.emotional_impact,
        )

        # Step 1: LLM に CharacterState 全体を生成させる (離散変数のため)
        llm_state = await self._client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=CharacterState,
            temperature=self._config.initial_temperature,
        )

        # Step 2: LLM 出力から delta を抽出し、数式で連続変数を統合
        llm_delta = EmotionalDelta(
            fatigue=llm_state.fatigue - prev_state.fatigue,
            motivation=llm_state.motivation - prev_state.motivation,
            stress=llm_state.stress - prev_state.stress,
        )

        merged_state = compute_next_state(
            prev_state=prev_state,
            event=event,
            llm_delta=llm_delta,
            config=self._config.state_transition,
            sensitivity=self._config.emotion_sensitivity,
        )

        # Step 3: 離散変数は LLM の出力を採用
        new_state = merged_state.model_copy(
            update={
                "current_focus": llm_state.current_focus,
                "unresolved_issue": llm_state.unresolved_issue,
                "growth_theme": llm_state.growth_theme,
                "memory_buffer": llm_state.memory_buffer,
                "relationships": llm_state.relationships,
            },
        )

        logger.info(
            "[Day %d] Phase 1: State Update ... OK (fatigue=%.2f, motivation=%.2f, stress=%.2f)",
            event.day,
            new_state.fatigue,
            new_state.motivation,
            new_state.stress,
        )

        delta_reason = self._generate_delta_reason(prev_state, new_state, event)

        return new_state, delta_reason

    async def generate_diary(
        self,
        state: CharacterState,
        event: DailyEvent,
        revision_instruction: str | None = None,
        long_term_context: dict[str, Any] | None = None,  # LongTermMemory の構造が可変のため Any を許容
        temperature: float | None = None,
        prev_endings: list[str] | None = None,
    ) -> str:
        """Phase 2: 更新された状態に基づきブログ日記本文を生成する。

        System_Persona.md を System Prompt として、Prompt_Generator.md を
        テンプレート展開した User Prompt を構築し、LLM にプレーンテキスト
        生成を依頼する。

        Args:
            state: 今日のキャラクター内部状態 (h_t)。
            event: 当日のイベント定義 (x_t)。
            revision_instruction: Critic からの修正指示 (リトライ時のみ)。
            long_term_context: 長期記憶コンテキスト(信念・テーマ・転換点)。None の場合は注入しない。
            temperature: 生成時の Temperature。None の場合は config のデフォルト値を使用。
            prev_endings: 直近の日記の余韻リスト。反復回避のためプロンプトに注入する。

        Returns:
            生成されたブログ日記テキスト (Markdown)。

        Raises:
            ValueError: 生成結果が空文字列の場合。
            FileNotFoundError: プロンプトファイルが見つからない場合。
        """
        system_prompt = load_prompt(self._prompts_dir, "System_Persona.md")
        user_prompt = self._build_generator_prompt(
            state, event, revision_instruction, long_term_context, prev_endings,
        )

        logger.debug(
            "Phase 2: generate_diary called (day=%d, revision=%s)",
            event.day,
            "yes" if revision_instruction else "no",
        )

        diary_text = await self._client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else self._config.initial_temperature,
        )

        logger.info(
            "[Day %d] Phase 2: Content Generation ... OK (%d chars)",
            event.day,
            len(diary_text),
        )

        return diary_text

    def _generate_delta_reason(
        self,
        prev_state: CharacterState,
        new_state: CharacterState,
        event: DailyEvent,
    ) -> str:
        """delta の変化理由をヒューリスティックで生成する。"""
        deltas = {
            "fatigue": new_state.fatigue - prev_state.fatigue,
            "motivation": new_state.motivation - prev_state.motivation,
            "stress": new_state.stress - prev_state.stress,
        }
        max_param = max(deltas, key=lambda k: abs(deltas[k]))
        direction = "上昇" if deltas[max_param] > 0 else "低下"
        return f"{event.description[:50]}により{max_param}が{direction}(delta={deltas[max_param]:.2f})"

    def _build_state_update_prompt(
        self,
        prev_state: CharacterState,
        event: DailyEvent,
        long_term_context: dict[str, Any] | None = None,  # LongTermMemory の構造が可変のため Any を許容
    ) -> str:
        """Phase 1 用の User Prompt を構築する。

        Prompt_StateUpdate.md をテンプレートとして読み込み、
        プレースホルダを動的データで展開する。

        Args:
            prev_state: 前日のキャラクター内部状態。
            event: 当日のイベント定義。
            long_term_context: 長期記憶コンテキスト。

        Returns:
            展開済みの User Prompt テキスト。
        """
        template = load_prompt(self._prompts_dir, "Prompt_StateUpdate.md")
        memory = "\n".join(prev_state.memory_buffer) or "(記憶なし)"

        prompt = template.format(
            previous_state=prev_state.model_dump_json(indent=2),
            event=event.model_dump_json(indent=2),
            memory_buffer=memory,
        )

        if long_term_context:
            prompt += self._format_long_term_context(long_term_context)

        return prompt

    def _build_generator_prompt(
        self,
        state: CharacterState,
        event: DailyEvent,
        revision: str | None,
        long_term_context: dict[str, Any] | None = None,  # LongTermMemory の構造が可変のため Any を許容
        prev_endings: list[str] | None = None,
    ) -> str:
        """Phase 2 用の User Prompt を構築する。

        Prompt_Generator.md をテンプレートとして読み込み、
        プレースホルダを動的データで展開する。

        Args:
            state: 今日のキャラクター内部状態。
            event: 当日のイベント定義。
            revision: Critic からの修正指示。None の場合は空文字列。
            long_term_context: 長期記憶コンテキスト。
            prev_endings: 直近の日記の余韻リスト。

        Returns:
            展開済みの User Prompt テキスト。
        """
        template = load_prompt(self._prompts_dir, "Prompt_Generator.md")
        memory = "\n".join(state.memory_buffer) or "(記憶なし)"
        revision_section = f"## 修正指示\n{revision}" if revision else ""

        if prev_endings:
            endings_text = "\n".join(f"- {e}" for e in prev_endings)
            endings_section = (
                "## 過去の余韻(使用済み)\n"
                "以下は直近の日記の締めくくりです。"
                "これらと同じ文・同じフレーズ・同じイメージでの締めくくりは避けてください。\n"
                f"{endings_text}"
            )
        else:
            endings_section = ""

        prompt = template.format(
            current_state=state.model_dump_json(indent=2),
            event=event.model_dump_json(indent=2),
            memory_buffer=memory,
            revision_instruction=revision_section,
            prev_endings=endings_section,
        )

        if long_term_context:
            prompt += self._format_long_term_context(long_term_context)

        return prompt

    @staticmethod
    # MemoryManager.get_context_for_actor() の戻り値型に依存
    def _format_long_term_context(context: dict[str, Any]) -> str:
        """長期記憶コンテキストをプロンプト用テキストに整形する。"""
        sections: list[str] = ["\n\n---\n\n## 長期記憶 (これまでの蓄積)\n"]

        beliefs: list[str] = context.get("beliefs", [])
        if beliefs:
            sections.append("### とこみの信念")
            for b in beliefs:
                sections.append(f"- {b}")

        themes: list[str] = context.get("recurring_themes", [])
        if themes:
            sections.append("\n### 繰り返し現れるテーマ")
            for t in themes:
                sections.append(f"- {t}")

        # MemoryManager.get_context_for_actor() の戻り値型に依存
        turning_points: list[dict[str, Any]] = context.get("turning_points", [])
        if turning_points:
            sections.append("\n### 転換点")
            for tp in turning_points:
                sections.append(f"- Day {tp['day']}: {tp['summary']}")

        if len(sections) == 1:
            return ""

        return "\n".join(sections)
