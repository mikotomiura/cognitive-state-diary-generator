"""2層メモリ構造モジュール.

ShortTermMemory (直近N日の生テキスト) と LongTermMemory (信念・テーマ・転換点)
を統合管理し, Actor/Critic にコンテキストを提供する.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from csdg.engine.prompt_loader import load_prompt
from csdg.schemas import LongTermMemory, Memory, MemoryExtraction, ShortTermMemory, TurningPoint

if TYPE_CHECKING:
    from csdg.engine.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SUMMARY_LENGTH = 100
_MAX_BELIEFS = 10
_MAX_THEMES = 5


class MemoryManager:
    """2層メモリの管理を担当する.

    Attributes:
        _memory: 現在のメモリ状態.
        _window_size: 短期記憶のウィンドウサイズ.
    """

    def __init__(
        self,
        window_size: int = 3,
        memory: Memory | None = None,
        prompts_dir: Path | None = None,
        temperature_final: float = 0.3,
    ) -> None:
        """MemoryManager を初期化する.

        Args:
            window_size: 短期記憶のウィンドウサイズ.
            memory: 初期メモリ状態. None の場合はデフォルトで生成.
            prompts_dir: プロンプトファイルのディレクトリパス.
            temperature_final: メモリ抽出 LLM 呼び出し時の Temperature.
        """
        self._window_size = window_size
        self._memory = memory or Memory(
            short_term=ShortTermMemory(window_size=window_size),
            long_term=LongTermMemory(),
        )
        self._prompts_dir = prompts_dir or Path("prompts")
        self._temperature_final = temperature_final

    @property
    def memory(self) -> Memory:
        """現在のメモリ状態を返す."""
        return self._memory

    def get_context_for_actor(self) -> dict[str, object]:
        """Actor プロンプトに渡すコンテキストを構築する.

        Returns:
            short_term と long_term の両方を含む辞書.
        """
        return {
            "short_term_entries": self._memory.short_term.entries,
            "beliefs": self._memory.long_term.beliefs,
            "recurring_themes": self._memory.long_term.recurring_themes,
            "turning_points": [{"day": tp.day, "summary": tp.summary} for tp in self._memory.long_term.turning_points],
        }

    def get_context_for_critic(self) -> dict[str, object]:
        """Critic (LLMJudge) に渡す長期記憶コンテキストを構築する.

        Returns:
            long_term の信念・テーマ情報.
        """
        return {
            "beliefs": self._memory.long_term.beliefs,
            "recurring_themes": self._memory.long_term.recurring_themes,
        }

    def update_short_term(self, diary_text: str, day: int) -> list[str]:
        """短期記憶に当日の要約を追加し, 押し出されたエントリを返す.

        Args:
            diary_text: 当日の日記テキスト.
            day: 経過日数.

        Returns:
            ウィンドウから押し出されたエントリのリスト (空の場合もある).
        """
        summary = f"[Day {day}] {diary_text[:_SUMMARY_LENGTH]}..."
        entries = [*self._memory.short_term.entries, summary]

        evicted: list[str] = []
        if len(entries) > self._window_size:
            overflow = len(entries) - self._window_size
            evicted = entries[:overflow]
            entries = entries[overflow:]

        self._memory = self._memory.model_copy(
            update={
                "short_term": ShortTermMemory(
                    window_size=self._window_size,
                    entries=entries,
                ),
            },
        )

        return evicted

    async def update_after_day(
        self,
        diary_text: str,
        day: int,
        llm_client: LLMClient | None = None,
    ) -> None:
        """Day 完了後にメモリを更新する.

        1. short_term に追加 (ウィンドウ超過分を evict)
        2. evict されたエントリから重要な信念・テーマを抽出して long_term に蓄積
        3. 当日の日記全文に対しても転換点キーワード検索を行う
        4. long_term の beliefs が多すぎる場合は古いものを統合・削除

        Args:
            diary_text: 当日の日記テキスト.
            day: 経過日数.
            llm_client: LLM クライアント (None の場合は簡易抽出).
        """
        evicted = self.update_short_term(diary_text, day)

        if evicted:
            await self._extract_to_long_term(evicted, day, llm_client)

        # 転換点キーワード検索は切り詰め前の原文に対しても行う
        # (短期記憶の summary は 100 文字に切り詰められるため、
        #  後半に現れるキーワードを見逃す問題を防ぐ)
        self._detect_turning_point_from_full_text(diary_text, day)

        self._compact_long_term()

        logger.info(
            "[Memory] Day %d updated (short_term=%d, beliefs=%d, themes=%d, turning_points=%d)",
            day,
            len(self._memory.short_term.entries),
            len(self._memory.long_term.beliefs),
            len(self._memory.long_term.recurring_themes),
            len(self._memory.long_term.turning_points),
        )

    async def _extract_to_long_term(
        self,
        evicted_entries: list[str],
        current_day: int,
        llm_client: LLMClient | None,
    ) -> None:
        """evict されたエントリから信念・テーマを抽出する.

        MVP では簡易的なルールベース抽出を行う.
        将来的には LLM を使って抽出精度を向上させる.
        """
        for entry in evicted_entries:
            # 転換点の検出: 高インパクトイベントの痕跡
            if any(kw in entry for kw in ("転機", "変化", "気づ", "決意", "覚悟")):
                tp = TurningPoint(
                    day=self._extract_day_from_entry(entry),
                    summary=entry[:_SUMMARY_LENGTH],
                )
                if not self._has_duplicate_turning_point(tp.day):
                    new_tps = [*self._memory.long_term.turning_points, tp]
                    self._memory = self._memory.model_copy(
                        update={
                            "long_term": self._memory.long_term.model_copy(
                                update={"turning_points": new_tps},
                            ),
                        },
                    )

        if llm_client is not None:
            await self._llm_extract_beliefs_and_themes(evicted_entries, llm_client)

    async def _llm_extract_beliefs_and_themes(
        self,
        evicted_entries: list[str],
        llm_client: LLMClient,
    ) -> None:
        """LLM を使って信念・テーマを抽出する.

        Prompt_MemoryExtract.md を使用し、evict されたエントリから
        長期的に保持すべき信念・テーマを抽出する。
        LLM 呼び出し失敗時はログ出力のみで続行する。
        """
        try:
            prompt_path = self._prompts_dir / "Prompt_MemoryExtract.md"
            if not prompt_path.exists():
                logger.warning(
                    "[Memory] Prompt_MemoryExtract.md not found, skipping LLM extraction",
                )
                return

            template = prompt_path.read_text(encoding="utf-8")
            user_prompt = template.format(
                evicted_entries="\n".join(evicted_entries),
                current_beliefs="\n".join(self._memory.long_term.beliefs) or "(なし)",
                current_themes="\n".join(
                    self._memory.long_term.recurring_themes,
                )
                or "(なし)",
            )

            extraction = await llm_client.generate_structured(
                system_prompt=self._load_system_prompt(),
                user_prompt=user_prompt,
                response_model=MemoryExtraction,
                temperature=self._temperature_final,
            )

            for belief in extraction.new_beliefs:
                self.add_belief(belief)
            for theme in extraction.new_themes:
                self.add_theme(theme)

            logger.info(
                "[Memory] LLM extracted %d beliefs, %d themes",
                len(extraction.new_beliefs),
                len(extraction.new_themes),
            )
        except (ValidationError, ValueError, OSError):  # LLM API / パース / IO エラーに限定
            logger.warning(
                "[Memory] LLM extraction failed, continuing with rule-based only",
                exc_info=True,
            )

    def add_belief(self, belief: str) -> None:
        """信念を long_term に追加する (重複チェック付き).

        Args:
            belief: 追加する信念テキスト.
        """
        existing = self._memory.long_term.beliefs
        if belief not in existing:
            new_beliefs = [*existing, belief]
            self._memory = self._memory.model_copy(
                update={
                    "long_term": self._memory.long_term.model_copy(
                        update={"beliefs": new_beliefs},
                    ),
                },
            )

    def add_theme(self, theme: str) -> None:
        """テーマを long_term に追加する (重複チェック付き).

        Args:
            theme: 追加するテーマテキスト.
        """
        existing = self._memory.long_term.recurring_themes
        if theme not in existing:
            new_themes = [*existing, theme]
            self._memory = self._memory.model_copy(
                update={
                    "long_term": self._memory.long_term.model_copy(
                        update={"recurring_themes": new_themes},
                    ),
                },
            )

    def _compact_long_term(self) -> None:
        """long_term が上限を超えた場合に古いエントリを削除する."""
        lt = self._memory.long_term
        updated = False
        beliefs = lt.beliefs
        themes = lt.recurring_themes

        if len(beliefs) > _MAX_BELIEFS:
            beliefs = beliefs[-_MAX_BELIEFS:]
            updated = True

        if len(themes) > _MAX_THEMES:
            themes = themes[-_MAX_THEMES:]
            updated = True

        if updated:
            self._memory = self._memory.model_copy(
                update={
                    "long_term": lt.model_copy(
                        update={"beliefs": beliefs, "recurring_themes": themes},
                    ),
                },
            )

    def _detect_turning_point_from_full_text(self, diary_text: str, day: int) -> None:
        """日記全文からキーワードベースで転換点を検出する.

        短期記憶の summary は _SUMMARY_LENGTH で切り詰められるため、
        キーワードが後半に出現する場合に見逃す問題がある。
        この関数は切り詰め前の原文に対して検索を行い、補完する。
        """
        tp_keywords = ("転機", "変化", "気づ", "決意", "覚悟")
        if any(kw in diary_text for kw in tp_keywords) and not self._has_duplicate_turning_point(day):
            tp = TurningPoint(
                day=day,
                summary=diary_text[:_SUMMARY_LENGTH],
            )
            new_tps = [*self._memory.long_term.turning_points, tp]
            self._memory = self._memory.model_copy(
                update={
                    "long_term": self._memory.long_term.model_copy(
                        update={"turning_points": new_tps},
                    ),
                },
            )

    def _has_duplicate_turning_point(self, day: int) -> bool:
        """指定 Day の転換点が既に存在するかチェックする."""
        return any(tp.day == day for tp in self._memory.long_term.turning_points)

    @staticmethod
    def _extract_day_from_entry(entry: str) -> int:
        """エントリから Day 番号を抽出する. 抽出できない場合は 0."""
        if "[Day " in entry:
            try:
                start = entry.index("[Day ") + 5
                end = entry.index("]", start)
                return int(entry[start:end])
            except (ValueError, IndexError):
                pass
        return 0

    def _load_system_prompt(self) -> str:
        """メモリ管理用のシステムプロンプトを読み込む.

        System_MemoryManager.md が見つからない場合はフォールバック文字列を返す.
        """
        try:
            return load_prompt(self._prompts_dir, "System_MemoryManager.md")
        except FileNotFoundError:
            logger.debug("[Memory] System_MemoryManager.md not found, using fallback system prompt")
            return "あなたは記憶管理システムです。"

    def get_memory_buffer_for_state(self) -> list[str]:
        """CharacterState.memory_buffer に設定する値を返す.

        既存の CharacterState との後方互換性のため,
        short_term.entries をそのまま返す.
        """
        return list(self._memory.short_term.entries)
