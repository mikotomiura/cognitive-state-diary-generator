"""
Actor モジュール -- Phase 1 (状態遷移) と Phase 2 (日記生成) を担当する。

architecture.md §3.1, §3.2, §6 に準拠し、LLMClient を介して LLM を呼び出す。
プロンプトは prompts/ ディレクトリの外部 Markdown ファイルから読み込み、
プレースホルダをテンプレート展開して使用する。
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, cast

from csdg.engine.constants import (
    ENDING_PATTERN_EXAMPLES,
    OPENING_PATTERN_EXAMPLES,
    SCENE_MARKER_HARD_DAYS,
    SCENE_MARKER_SOFT_DAYS,
    THEME_WORD_HARD_LIMIT,
    THEME_WORD_PER_DAY_LIMIT,
    THEME_WORD_SOFT_LIMIT,
)
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
        long_term_context: dict[str, object] | None = None,
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
        long_term_context: dict[str, object] | None = None,
        temperature: float | None = None,
        prev_endings: list[str] | None = None,
        prev_images: list[str] | None = None,
        used_openings: list[str] | None = None,
        used_structures: list[str] | None = None,
        used_philosophers: dict[str, int] | None = None,
        used_ending_patterns: list[str] | None = None,
        theme_word_totals: dict[str, int] | None = None,
        prev_rhetorical: list[str] | None = None,
        scene_marker_days: dict[str, int] | None = None,
        prev_openings_text: list[str] | None = None,
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
            prev_images: 過去の日記で使用されたシーン描写。反復回避のためプロンプトに注入する。
            used_openings: 過去の日記で使用された書き出しパターン。反復回避のためプロンプトに注入する。
            used_structures: 過去の日記で使用された場面構造パターン。反復回避のためプロンプトに注入する。
            used_philosophers: 哲学者・思想家の使用回数辞書。反復回避のためプロンプトに注入する。
            used_ending_patterns: 過去の余韻構文パターン。反復回避のためプロンプトに注入する。
            theme_word_totals: 主題語の累計使用回数。頻度制限のためプロンプトに注入する。
            prev_rhetorical: 過去の修辞疑問文。反復回避のためプロンプトに注入する。
            scene_marker_days: シーンマーカーの出現日数。反復回避のためプロンプトに注入する。
            prev_openings_text: 過去の冒頭テキストリスト。テキストレベル重複回避のためプロンプトに注入する。

        Returns:
            生成されたブログ日記テキスト (Markdown)。

        Raises:
            ValueError: 生成結果が空文字列の場合。
            FileNotFoundError: プロンプトファイルが見つからない場合。
        """
        system_prompt = load_prompt(self._prompts_dir, "System_Persona.md")
        user_prompt = self._build_generator_prompt(
            state,
            event,
            revision_instruction,
            long_term_context,
            prev_endings,
            prev_images,
            used_openings,
            used_structures,
            used_philosophers,
            used_ending_patterns,
            theme_word_totals,
            prev_rhetorical,
            scene_marker_days,
            prev_openings_text,
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
            max_tokens=512,
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
        long_term_context: dict[str, object] | None = None,
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
        long_term_context: dict[str, object] | None = None,
        prev_endings: list[str] | None = None,
        prev_images: list[str] | None = None,
        used_openings: list[str] | None = None,
        used_structures: list[str] | None = None,
        used_philosophers: dict[str, int] | None = None,
        used_ending_patterns: list[str] | None = None,
        theme_word_totals: dict[str, int] | None = None,
        prev_rhetorical: list[str] | None = None,
        scene_marker_days: dict[str, int] | None = None,
        prev_openings_text: list[str] | None = None,
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
            prev_images: 過去の日記で使用されたシーン描写。
            used_openings: 過去の日記で使用された書き出しパターン。
            used_structures: 過去の日記で使用された場面構造パターン。
            used_philosophers: 哲学者・思想家の使用回数辞書。
            used_ending_patterns: 過去の余韻構文パターン。
            theme_word_totals: 主題語の累計使用回数。
            prev_rhetorical: 過去の修辞疑問文。
            scene_marker_days: シーンマーカーの出現日数。
            prev_openings_text: 過去の冒頭テキストリスト。

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

        if prev_images:
            images_text = "\n".join(f"- {img}" for img in prev_images)
            images_section = (
                "## 使用済みシーン描写\n"
                "以下は過去の日記で使用された場面描写・イメージです。\n"
                "**これらと同じ場面・同じ物・同じシチュエーションを再度使わないでください。**\n"
                "別の場所、別の物、別の感覚で場面を構成してください。\n"
                f"{images_text}"
            )
        else:
            images_section = ""

        # 書き出しパターンのホワイトリスト + 具体例注入
        openings_section = ""
        if used_openings:
            openings_text = "\n".join(f"- {o}" for o in used_openings)
            opening_counts: Counter[str] = Counter()
            for o in used_openings:
                if ": " in o:
                    opening_counts[o.split(": ", 1)[1]] += 1
            opening_limits: dict[str, int] = {"比喩型": 2}
            default_opening_limit = 3
            # 未使用パターンを優先的に推奨 (余韻パターンと同方式)
            available_opening_patterns: list[str] = []
            unused_opening_patterns: list[str] = []
            for op_name, example in OPENING_PATTERN_EXAMPLES.items():
                limit = opening_limits.get(op_name, default_opening_limit)
                cnt = opening_counts.get(op_name, 0)
                if cnt == 0:
                    unused_opening_patterns.append(f"- **{op_name}** (未使用・推奨): {example}")
                elif cnt < limit:
                    remaining = limit - cnt
                    available_opening_patterns.append(f"- {op_name} (残り{remaining}回): {example}")
            # 未使用パターンを先に配置して優先度を明示
            available_opening_patterns = unused_opening_patterns + available_opening_patterns
            diversity_note = ""
            if unused_opening_patterns:
                diversity_note = (
                    "\n**多様性のため、まだ使っていないパターン (「未使用・推奨」) を優先的に選んでください。**\n"
                )
            openings_section = (
                "## 書き出しパターンの指定\n"
                f"過去の使用状況:\n{openings_text}\n\n"
                "**【必須】今日の書き出しは、以下の使用可能パターンのいずれかで"
                "始めてください:**\n" + diversity_note + "\n".join(available_opening_patterns)
            )
        else:
            all_ops = [f"- **{op_name}**: {example}" for op_name, example in OPENING_PATTERN_EXAMPLES.items()]
            openings_section = (
                "## 書き出しパターンの指定\n"
                "**【必須】今日の書き出しは、以下のパターンのいずれかで"
                "始めてください (毎日異なるパターンを使うこと):**\n" + "\n".join(all_ops)
            )

        # 改善案5: プロンプト冒頭に配置する禁止事項を組み立て
        critical_lines: list[str] = []

        # 感情決壊モード: emotional_impact の絶対値が 0.7 を超える場合
        if abs(event.emotional_impact) > 0.7:
            critical_lines.append(
                "- **【感情決壊モード】** emotional_impact の絶対値が 0.7 を超えています。"
                " 以下を **必ず** 満たしてください:\n"
                "  (a) 8文字以下の短文を3回以上連続させるパートを最低1箇所含める"
                " (例: 「無理。意味わからない。なんでわたしは。」)\n"
                "  (b) 口語表現 (「ムカつく」「普通に嫌」「意味わからん」等) を3回以上使う\n"
                "  (c) 哲学的考察を試みて途中で感情に呑まれて中断する\n"
                "  (d) タイトルは短い叫び・独り言にする (例: 「# うるさい」「# 1年前のわたしへ」)\n"
                "  これらに違反した場合は無条件で却下されます"
            )

        # 文字数制約 (最重要)
        critical_lines.append(
            "- **【文字数厳守】** 本文 (タイトル行を除く) は **300〜350文字** に収めてください。"
            " 350文字を超えたら長すぎます。3段落構成を目安に凝縮してください"
        )

        # 読者への語りかけ必須
        critical_lines.append("- 本文中に読者への語りかけ (問いかけ・共感の誘い・弁明など) を最低1回含めてください")

        if used_ending_patterns:
            ep_counts: Counter[str] = Counter()
            for p in used_ending_patterns:
                if ": " in p:
                    ep_counts[p.split(": ", 1)[1]] += 1
            forbidden_ep = [name for name, cnt in ep_counts.items() if cnt >= 2]
            if forbidden_ep:
                critical_lines.append(f"- 余韻に「{'」「'.join(forbidden_ep)}」は使用禁止 (上限到達)")
        if used_structures:
            prev_day_structure = ""
            last_s = used_structures[-1]
            if ": " in last_s:
                prev_day_structure = last_s.split(": ", 1)[1]
            if prev_day_structure and prev_day_structure != "その他":
                critical_lines.append(f"- 場面構造に「{prev_day_structure}」は使用禁止 (前日と同一)")
            sc_counts: Counter[str] = Counter()
            for s in used_structures:
                if ": " in s:
                    sc_counts[s.split(": ", 1)[1]] += 1
            struct_limits: dict[str, int] = {"古書店型": 2, "帰路型": 2}
            for sn, sc in sc_counts.items():
                sl = struct_limits.get(sn, 3)
                if sc >= sl and sn != prev_day_structure:
                    critical_lines.append(f"- 場面構造に「{sn}」は使用禁止 (上限{sl}回到達)")
        if used_openings:
            op_counts: Counter[str] = Counter()
            for o in used_openings:
                if ": " in o:
                    op_counts[o.split(": ", 1)[1]] += 1
            op_limits: dict[str, int] = {"比喩型": 2}
            forbidden_op = [name for name, cnt in op_counts.items() if cnt >= op_limits.get(name, 3)]
            if forbidden_op:
                critical_lines.append(f"- 書き出しに「{'」「'.join(forbidden_op)}」は使用禁止 (上限到達)")

        # 書き出し・余韻パターンの必須遵守を常に追加
        critical_lines.append(
            "- 書き出しは必ず「書き出しパターンの指定」セクションに記載された"
            "パターンのいずれかで始めてください。"
            "冒頭1文目の最初の40文字以内にパターンの特徴語を含めてください"
        )
        critical_lines.append(
            "- 余韻は必ず「余韻パターンの指定」セクションに記載されたパターンのいずれかで締めくくってください"
        )

        constraints_text = (
            "## 【最重要】今日の禁止事項・必須事項\n\n"
            "以下は絶対に守るべき制約です。\n"
            "**これらに違反した日記は無条件で却下されます:**\n\n" + "\n".join(critical_lines)
        )

        prompt = template.format(
            current_state=state.model_dump_json(indent=2),
            event=event.model_dump_json(indent=2),
            memory_buffer=memory,
            revision_instruction=revision_section,
            prev_endings=endings_section,
            prev_images=images_section,
            used_openings=openings_section,
            critical_constraints=constraints_text,
        )

        # 改善案1: 場面構造パターンの全パターン追跡 + 連続使用検出
        if used_structures:
            structures_text = "\n".join(f"- {s}" for s in used_structures)
            structure_counts: Counter[str] = Counter()
            for s in used_structures:
                if ": " in s:
                    structure_counts[s.split(": ", 1)[1]] += 1

            struct_pattern_limits: dict[str, int] = {"古書店型": 2, "帰路型": 2}
            struct_default_limit = 3
            struct_warnings: list[str] = []
            for pattern_name, cnt in structure_counts.items():
                limit = struct_pattern_limits.get(pattern_name, struct_default_limit)
                if cnt >= limit:
                    struct_warnings.append(f"\n**「{pattern_name}」は上限({limit}回)に達しました。使用禁止です。**")
            # 連続使用の禁止
            prev_structure = ""
            if used_structures:
                last_entry = used_structures[-1]
                if ": " in last_entry:
                    prev_structure = last_entry.split(": ", 1)[1]
            if prev_structure and prev_structure != "その他":
                struct_warnings.append(
                    f"\n**前日の場面構造は「{prev_structure}」でした。"
                    "今日は異なる構造を使ってください (連続使用禁止)。**"
                )
            # 使用可能な構造の提示
            all_structures = [
                "古書店型",
                "会議型",
                "帰路型",
                "自室内省型",
                "移動中思索型",
                "対話中心型",
                "回想主導型",
            ]
            forbidden_structs = {
                p for p, c in structure_counts.items() if c >= struct_pattern_limits.get(p, struct_default_limit)
            }
            if prev_structure and prev_structure != "その他":
                forbidden_structs.add(prev_structure)
            available_structs = [p for p in all_structures if p not in forbidden_structs]
            if available_structs:
                struct_warnings.append(f"\n**今日使用可能な場面構造:** {'、'.join(available_structs)}")
            prompt += (
                "\n\n---\n\n## 使用済み場面構造パターン\n"
                "以下は過去の日記で使った場面構造です。\n"
                f"{structures_text}{''.join(struct_warnings)}"
            )

        # 哲学者・思想家の使用状況の注入
        if used_philosophers:
            phil_lines: list[str] = []
            for name, count in sorted(used_philosophers.items()):
                if count >= 2:
                    phil_lines.append(f"- {name}: {count}回 (上限に達しました — 以降の日記では使用禁止)")
                else:
                    phil_lines.append(f"- {name}: {count}回")
            phil_text = "\n".join(phil_lines)
            prompt += (
                "\n\n---\n\n## 使用済み哲学者・思想家\n"
                "以下の人物は既に言及されています。**同一人物への言及は7日間で最大2回まで**です。\n"
                f"{phil_text}"
            )

        # 改善案2: 余韻パターンのホワイトリスト + 具体例注入
        if used_ending_patterns:
            patterns_text = "\n".join(f"- {p}" for p in used_ending_patterns)
            pattern_counts: Counter[str] = Counter()
            for p in used_ending_patterns:
                if ": " in p:
                    pattern_counts[p.split(": ", 1)[1]] += 1
            # 使用可能パターンの計算 (上限2回)
            # 未使用パターンを優先的に推奨
            available_patterns: list[str] = []
            unused_patterns: list[str] = []
            for ep_name, example in ENDING_PATTERN_EXAMPLES.items():
                cnt = pattern_counts.get(ep_name, 0)
                if cnt == 0:
                    unused_patterns.append(f"- **{ep_name}** (未使用・推奨): {example}")
                elif cnt < 2:
                    available_patterns.append(f"- {ep_name} (残り{2 - cnt}回): {example}")
            # 未使用パターンを先に配置して優先度を明示
            available_patterns = unused_patterns + available_patterns
            diversity_note = ""
            if unused_patterns:
                diversity_note = (
                    "\n**多様性のため、まだ使っていないパターン (「未使用・推奨」) を優先的に選んでください。**\n"
                )
            prompt += (
                "\n\n---\n\n## 余韻パターンの指定\n"
                "過去の使用状況:\n"
                f"{patterns_text}\n\n"
                "**【必須】今日の余韻は、以下の使用可能パターンのいずれかで"
                "締めくくってください:**\n" + diversity_note + "\n".join(available_patterns)
            )
        else:
            # Day 1: 全パターン提示
            all_ep = [f"- **{ep_name}**: {example}" for ep_name, example in ENDING_PATTERN_EXAMPLES.items()]
            prompt += (
                "\n\n---\n\n## 余韻パターンの指定\n"
                "**【必須】今日の余韻は、以下のパターンのいずれかで"
                "締めくくってください (毎日異なるパターンを使うこと):**\n" + "\n".join(all_ep)
            )

        # 主題語の使用状況の注入 (累計がなくても per-day 制限は常時注入)
        has_theme_data = theme_word_totals is not None and any(v > 0 for v in theme_word_totals.values())
        word_lines: list[str] = []
        if has_theme_data and theme_word_totals is not None:
            for word, total in sorted(theme_word_totals.items()):
                if total <= 0:
                    continue
                if total >= THEME_WORD_HARD_LIMIT:
                    word_lines.append(f"- 「{word}」: これまで{total}回使用(上限超過)→ **今日は使用禁止**")
                elif total >= THEME_WORD_SOFT_LIMIT:
                    remaining = max(0, THEME_WORD_HARD_LIMIT - total)
                    per_day = min(THEME_WORD_PER_DAY_LIMIT, remaining)
                    word_lines.append(
                        f"- 「{word}」: これまで{total}回使用(上限目安: {THEME_WORD_HARD_LIMIT}回)"
                        f"→ 今日は{per_day}回以下に抑えてください"
                    )
                else:
                    word_lines.append(f"- 「{word}」: これまで{total}回使用")
        # per-day 制限は常時注入 (コールドスタート対策)
        prompt += (
            "\n\n---\n\n## 主題語の使用状況\n"
            f"**今日の日記では各主題語を{THEME_WORD_PER_DAY_LIMIT}回以下にしてください。**\n"
            "意識的に他の表現に言い換えてください。\n"
        )
        if word_lines:
            words_text = "\n".join(word_lines)
            prompt += f"{words_text}\n"
        prompt += "代替表現の例: 「速さ」「生産性」「合理性」「最短距離」「無駄のなさ」"
        # イベント記述に含まれる主題語への警告
        event_theme_words = [w for w in ("効率", "非効率", "最適化", "自動化") if w in event.description]
        if event_theme_words:
            prompt += (
                f"\n**注意:** 今日のイベントに「{'」「'.join(event_theme_words)}」が含まれていますが、"
                "日記本文ではこれらの語を直接使わず代替表現に置き換えてください。"
            )

        # 修辞疑問文の注入
        if prev_rhetorical:
            rhetorical_text = "\n".join(f"- 「{q}」" for q in prev_rhetorical)
            prompt += (
                "\n\n---\n\n## 使用済み修辞疑問文\n"
                "以下は過去の日記で使った問いかけです。\n"
                "**同じ問いかけ・同じ構文の問いかけを再度使わないでください。**\n"
                f"{rhetorical_text}"
            )

        # シーンマーカーの過剰使用制限
        if scene_marker_days:
            overused: list[str] = []
            for marker, days in sorted(scene_marker_days.items()):
                if days >= SCENE_MARKER_HARD_DAYS:
                    overused.append(f"- 「{marker}」: {days}日間で使用 → **今日は使用禁止**")
                elif days >= SCENE_MARKER_SOFT_DAYS:
                    overused.append(f"- 「{marker}」: {days}日間で使用 → 今日は使用を控えてください")
            if overused:
                overused_text = "\n".join(overused)
                prompt += (
                    "\n\n---\n\n## 過剰使用シーンマーカー\n"
                    "以下の場所・物は過去の日記で繰り返し使われています。\n"
                    "**別の場所・物・感覚で場面を構成してください。**\n"
                    f"{overused_text}"
                )

        # 過去の冒頭テキスト注入 (テキストレベル重複禁止)
        if prev_openings_text:
            opening_texts = "\n".join(f"- Day {i + 1}: 「{t}」" for i, t in enumerate(prev_openings_text))
            prompt += (
                "\n\n---\n\n## 過去の書き出しテキスト (テキストレベル重複禁止)\n"
                "以下は過去の日記の冒頭文です。\n"
                "**これらと同じ文・同じフレーズで書き出すことは絶対に禁止です。**\n"
                "パターンが同じでも、テキストは完全に異なるものにしてください。\n"
                f"{opening_texts}"
            )

        if long_term_context:
            prompt += self._format_long_term_context(long_term_context)

        return prompt

    @staticmethod
    def _format_long_term_context(context: dict[str, object]) -> str:
        """長期記憶コンテキストをプロンプト用テキストに整形する。

        Note:
            引数の型は MemoryManager.get_context_for_actor() の戻り値型に依存する。
        """
        sections: list[str] = ["\n\n---\n\n## 長期記憶 (これまでの蓄積)\n"]

        beliefs = cast("list[str]", context.get("beliefs", []))
        if beliefs:
            sections.append("### とこみの信念")
            for b in beliefs:
                sections.append(f"- {b}")

        themes = cast("list[str]", context.get("recurring_themes", []))
        if themes:
            sections.append("\n### 繰り返し現れるテーマ")
            for t in themes:
                sections.append(f"- {t}")

        turning_points = cast("list[dict[str, object]]", context.get("turning_points", []))
        if turning_points:
            sections.append("\n### 転換点")
            for tp in turning_points:
                sections.append(f"- Day {tp['day']}: {tp['summary']}")

        if len(sections) == 1:
            return ""

        return "\n".join(sections)
