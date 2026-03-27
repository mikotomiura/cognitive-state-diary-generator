"""Pipeline モジュール -- 3-Phase パイプラインの実行制御。

architecture.md §3.4 (リトライ制御) および §4 (Self-Healing 設計) に準拠し、
Actor-Critic ループの制御、Temperature Decay、Best-of-N フォールバック、
メモリ管理を統合する。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic._exceptions import OverloadedError
from pydantic import ValidationError

from csdg.engine.critic import compute_deviation, compute_expected_delta, judge
from csdg.engine.critic_log import (
    CriticLog,
    CriticLogEntry,
    build_feedback_prompt,
    compute_text_hash,
    extract_failure_patterns,
)
from csdg.engine.memory import MemoryManager
from csdg.schemas import CharacterState, CriticScore, GenerationRecord, PipelineLog

if TYPE_CHECKING:
    from csdg.config import CSDGConfig
    from csdg.engine.actor import Actor
    from csdg.engine.critic import Critic
    from csdg.engine.llm_client import LLMClient
    from csdg.schemas import CriticResult, DailyEvent

logger = logging.getLogger(__name__)

_SCORE_FIELDS = ("temporal_consistency", "emotional_plausibility", "persona_deviation")
_PHASE_COUNT = 3
_MAX_CONSECUTIVE_FAILURES = 3
_MAX_OVERLOAD_RETRIES = 3
_OVERLOAD_BASE_DELAY_SEC = 30
_FALLBACK_DESCRIPTION_LENGTH = 50
_MAX_REVISION_LENGTH = 500
_MAX_PREV_ENDINGS = 3
_MAX_PREV_IMAGES = 5
_IMAGE_CLIP_LENGTH = 50

# シーンを構成する場所・物のマーカー語
_SCENE_MARKERS = (
    "古書店",
    "電車",
    "コンビニ",
    "会議室",
    "カフェ",
    "窓",
    "駅",
    "道",
    "部屋",
    "図書館",
    "公園",
    "蛍光灯",
    "缶コーヒー",
    "ノート",
    "本",
    "栞",
    "ペン",
    "キーボード",
    "明かり",
    "匂い",
    "自動販売機",
    "段ボール",
)

# 書き出しパターン分類用キーワード
_OPENING_METAPHOR_KEYWORDS = ("まるで", "のような", "ように")
_OPENING_SENSORY_KEYWORDS = ("匂い", "音", "光", "温度", "風", "空気", "肌")
_OPENING_RECALL_KEYWORDS = ("あの頃", "あの日", "大学院", "昔", "思い出", "記憶")


def _extract_key_images(diary_text: str, max_images: int = _MAX_PREV_IMAGES) -> list[str]:
    """日記テキストからシーンを構成するキーフレーズを抽出する。

    場所・物のマーカー語を含む文を検出し、短いクリップとして返す。
    Day 間で蓄積し、Generator プロンプトに「使用済みシーン」として注入することで
    イメージの反復を防止する。

    Args:
        diary_text: 日記テキスト全文。
        max_images: 返すキーフレーズの最大数。

    Returns:
        シーンのキーフレーズリスト。
    """
    images: list[str] = []
    seen_markers: set[str] = set()
    sentences = re.split(r"[。\n]", diary_text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 5:
            continue
        for marker in _SCENE_MARKERS:
            if marker in sentence and marker not in seen_markers:
                images.append(sentence[:_IMAGE_CLIP_LENGTH])
                seen_markers.add(marker)
                break
    return images[:max_images]


def _detect_opening_pattern(diary_text: str) -> str:
    """日記の冒頭から書き出しパターンを分類する。

    Prompt_Generator.md で定義された6パターン (比喩型/五感型/会話型/問い型/断片型/回想型)
    のいずれかに分類する。判定できない場合は「その他」を返す。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        パターン名の文字列。
    """
    first_line = diary_text.strip().split("\n")[0] if diary_text.strip() else ""
    head = first_line[:80]

    if any(kw in head for kw in _OPENING_METAPHOR_KEYWORDS):
        return "比喩型"
    if head.startswith(("\u300c", "\u300e")):  # 「 or 『
        return "会話型"
    if head.endswith(("?", "\uff1f", "\u3060\u308d\u3046\u304b")):  # ? / full-width ? / darouka
        return "問い型"
    if any(kw in head for kw in _OPENING_SENSORY_KEYWORDS):
        return "五感型"
    if any(kw in head for kw in _OPENING_RECALL_KEYWORDS):
        return "回想型"
    if first_line and len(first_line) < 30:
        return "断片型"
    return "その他"


def _extract_ending(diary_text: str) -> str:
    """日記テキストの末尾段落(余韻)を抽出する。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        末尾の非空段落。段落がない場合は空文字列。
    """
    paragraphs = [p.strip() for p in diary_text.strip().split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    return paragraphs[-1]


def _sanitize_revision(instruction: str | None) -> str | None:
    """revision_instruction の長さ制限・制御文字除去・デリミタ付与を行う。

    Critic LLM の出力が Actor プロンプトに注入されるため、
    制御文字の除去と XML デリミタによる範囲限定を行う。
    """
    if instruction is None:
        return None
    # 制御文字を除去 (改行・タブは許容)
    sanitized = "".join(c for c in instruction if c >= " " or c in "\n\t")
    sanitized = sanitized[:_MAX_REVISION_LENGTH]
    return f"<revision>\n{sanitized}\n</revision>"


def _total_score(score: CriticScore) -> int:
    """CriticScore の3スコア合計値を返す。"""
    return sum(getattr(score, f) for f in _SCORE_FIELDS)


@dataclass
class RetryCandidate:
    """リトライ候補を保持する。"""

    attempt: int
    temperature: float
    state: CharacterState
    diary_text: str
    critic_score: CriticScore
    total_score: int


class PipelineRunner:
    """3フェーズパイプラインの実行を制御する。

    Attributes:
        _config: パイプライン設定。
        _actor: Phase 1/2 を担当する Actor。
        _critic: Phase 3 を担当する Critic。
    """

    def __init__(
        self,
        config: CSDGConfig,
        actor: Actor,
        critic: Critic,
        memory_manager: MemoryManager | None = None,
        critic_log: CriticLog | None = None,
        prompts_dir: Path | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """PipelineRunner を初期化する。

        Args:
            config: パイプライン設定。
            actor: Actor インスタンス。
            critic: Critic インスタンス。
            memory_manager: メモリマネージャ。None の場合はデフォルトで生成。
            critic_log: Critic ログ。None の場合は空のログで生成。
            prompts_dir: プロンプトファイルのディレクトリパス。
            llm_client: LLM クライアント。メモリの LLM 抽出に使用する。
        """
        self._config = config
        self._actor = actor
        self._critic = critic
        self._memory = memory_manager or MemoryManager(
            window_size=config.memory_window_size,
            temperature_final=config.temperature_final,
        )
        self._critic_log = critic_log or CriticLog()
        self._llm_client = llm_client
        self._prompt_hashes = self._compute_prompt_hashes(prompts_dir or Path("prompts"))

    @property
    def critic_log(self) -> CriticLog:
        """Critic ログを返す。"""
        return self._critic_log

    async def run(
        self,
        events: list[DailyEvent],
        initial_state: CharacterState,
    ) -> PipelineLog:
        """全Dayのパイプラインを実行する。

        1. Day 1 から順に run_single_day() を呼び出す
        2. 各Day完了後に memory_buffer を更新 (スライディングウィンドウ)
        3. 連続3Day以上失敗したら中断
        4. PipelineLog を返す

        Args:
            events: 全Dayのイベントリスト。
            initial_state: 初期状態 (h_0)。

        Returns:
            パイプライン全体の実行ログ。
        """
        pipeline_start = time.monotonic()
        records: list[GenerationRecord] = []
        current_state = initial_state
        consecutive_failures = 0
        total_retries = 0
        total_fallbacks = 0
        prev_diary: str | None = None
        prev_endings: list[str] = []
        prev_images: list[str] = []
        used_openings: list[str] = []

        for event in events:
            day = event.day
            overload_attempts = 0
            day_success = False

            while overload_attempts <= _MAX_OVERLOAD_RETRIES:
                try:
                    record = await self.run_single_day(
                        event,
                        current_state,
                        day,
                        prev_diary=prev_diary,
                        prev_endings=list(prev_endings),
                        prev_images=list(prev_images),
                        used_openings=list(used_openings),
                    )
                    records.append(record)
                    total_retries += record.retry_count
                    if record.fallback_used:
                        total_fallbacks += 1

                    await self._memory.update_after_day(record.diary_text, day, llm_client=self._llm_client)
                    current_state = record.final_state.model_copy(
                        update={"memory_buffer": self._memory.get_memory_buffer_for_state()},
                    )
                    prev_diary = record.diary_text
                    ending = _extract_ending(record.diary_text)
                    if ending:
                        prev_endings.append(ending)
                        prev_endings = prev_endings[-_MAX_PREV_ENDINGS:]
                    # シーン描写の蓄積 (反復防止用)
                    new_images = _extract_key_images(record.diary_text)
                    prev_images.extend(new_images)
                    prev_images = prev_images[-_MAX_PREV_IMAGES:]
                    # 書き出しパターンの蓄積
                    opening = _detect_opening_pattern(record.diary_text)
                    used_openings.append(f"Day {day}: {opening}")
                    consecutive_failures = 0
                    day_success = True
                    break

                except OverloadedError:
                    overload_attempts += 1
                    if overload_attempts > _MAX_OVERLOAD_RETRIES:
                        logger.error(
                            "[Day %d] OverloadedError %d回リトライ後も回復せず -- Day をスキップ",
                            day,
                            _MAX_OVERLOAD_RETRIES,
                        )
                        break
                    delay = _OVERLOAD_BASE_DELAY_SEC * (2 ** (overload_attempts - 1))
                    logger.warning(
                        "[Day %d] OverloadedError (attempt %d/%d) -- %d秒待機後にリトライ",
                        day,
                        overload_attempts,
                        _MAX_OVERLOAD_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)

                except Exception:
                    logger.exception("[Day %d] 予期しない例外 -- Day をスキップ", day)
                    break

            if not day_success:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        "[CSDG] 連続 %d Day 失敗 -- パイプラインを中断",
                        consecutive_failures,
                    )
                    break

        pipeline_ms = int((time.monotonic() - pipeline_start) * 1000)
        # Phase 1: 各 Day 1回 (成功時) + Phase 2/3: 各 attempt 2回
        # Phase 1 のリトライは retry_count に含まれないため、最低1回として計上
        api_calls = sum(1 + (1 + r.retry_count) * 2 for r in records)

        logger.info(
            "[CSDG] Pipeline complete (%d/%d days, %d retries, %d fallbacks)",
            len(records),
            len(events),
            total_retries,
            total_fallbacks,
        )

        return PipelineLog(
            executed_at=datetime.now(tz=UTC),
            config_summary={
                "model": self._config.llm_model,
                "max_retries": self._config.max_retries,
                "initial_temperature": self._config.initial_temperature,
            },
            prompt_hashes=self._prompt_hashes,
            records=records,
            total_duration_ms=pipeline_ms,
            total_api_calls=api_calls,
            total_retries=total_retries,
            total_fallbacks=total_fallbacks,
        )

    async def run_single_day(
        self,
        event: DailyEvent,
        prev_state: CharacterState,
        day: int,
        prev_diary: str | None = None,
        prev_endings: list[str] | None = None,
        prev_images: list[str] | None = None,
        used_openings: list[str] | None = None,
    ) -> GenerationRecord:
        """1Dayのパイプラインを実行する。

        Phase 1: 状態遷移 (ValidationError → 最大3回リトライ → フォールバック)
        Phase 2 + Phase 3: 生成 → 評価 → リトライループ

        Args:
            event: 当日のイベント。
            prev_state: 前日のキャラクター内部状態。
            day: 経過日数。
            prev_diary: 前日の日記テキスト (trigram overlap チェック用)。
            prev_endings: 直近の日記の余韻リスト (反復回避用)。
            prev_images: 過去の日記で使用されたシーン描写 (反復回避用)。
            used_openings: 過去の日記で使用された書き出しパターン (反復回避用)。

        Returns:
            1Day分の生成記録。
        """
        fallback_used = False

        # --- Phase 1: State Update ---
        phase1_start = time.monotonic()
        curr_state: CharacterState | None = None

        # 長期記憶コンテキストを取得
        actor_context = self._memory.get_context_for_actor()

        delta_reason = ""
        for attempt in range(self._config.max_retries):
            try:
                curr_state, delta_reason = await self._actor.update_state(
                    prev_state,
                    event,
                    long_term_context=actor_context,
                )
                break
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "[Day %d] Phase 1: ValidationError (attempt %d/%d) -- %s",
                    day,
                    attempt + 1,
                    self._config.max_retries,
                    exc,
                )

        if curr_state is None:
            curr_state = self._create_fallback_state(prev_state, day, event)
            delta_reason = "フォールバック: 状態更新に失敗"
            fallback_used = True
            logger.warning("[Day %d] Fallback: Phase 1 前日状態コピー", day)

        phase1_ms = int((time.monotonic() - phase1_start) * 1000)
        logger.info("[Day %d] Phase 1: State Update ... OK (%.1fs)", day, phase1_ms / 1000)

        # --- Phase 2 + Phase 3: Generation-Evaluation Loop ---
        schedule = self._config.temperature_schedule
        candidates: list[RetryCandidate] = []
        all_scores: list[CriticScore] = []
        revision_instruction: str | None = None
        final_diary = ""
        phase2_total_ms = 0
        phase3_total_ms = 0
        last_critic_result: CriticResult | None = None

        # 過去の失敗パターンをフィードバックとして取得
        feedback = build_feedback_prompt(
            self._critic_log.get_all_low_score_patterns(threshold=3.0, top_k=5),
        )

        for attempt_idx in range(self._config.max_retries):
            temperature = schedule[attempt_idx] if attempt_idx < len(schedule) else schedule[-1]

            # Phase 2: Content Generation (過去の失敗パターンを注入)
            combined_instruction = revision_instruction or ""
            if feedback:
                combined_instruction = f"{combined_instruction}\n\n{feedback}" if combined_instruction else feedback

            phase2_start = time.monotonic()
            diary_text = await self._actor.generate_diary(
                curr_state,
                event,
                revision_instruction=combined_instruction or None,
                long_term_context=actor_context,
                temperature=temperature,
                prev_endings=prev_endings,
                prev_images=prev_images,
                used_openings=used_openings,
            )
            phase2_ms = int((time.monotonic() - phase2_start) * 1000)
            phase2_total_ms += phase2_ms
            logger.info("[Day %d] Phase 2: Content Generation ... OK (%.1fs)", day, phase2_ms / 1000)

            # Phase 3: Critic Evaluation (3層詳細結果を取得)
            phase3_start = time.monotonic()
            critic_result = await self._critic.evaluate_full(
                prev_state,
                curr_state,
                diary_text,
                event,
                prev_diary=prev_diary,
            )
            critic_score = critic_result.final_score
            last_critic_result = critic_result
            phase3_ms = int((time.monotonic() - phase3_start) * 1000)
            phase3_total_ms += phase3_ms
            all_scores.append(critic_score)

            total = _total_score(critic_score)
            candidate = RetryCandidate(
                attempt=attempt_idx,
                temperature=temperature,
                state=curr_state,
                diary_text=diary_text,
                critic_score=critic_score,
                total_score=total,
            )
            candidates.append(candidate)

            if judge(critic_score):
                logger.info(
                    "[Day %d] Phase 3: Critic Evaluation ... Pass (score: %d/%d/%d) (%.1fs)",
                    day,
                    critic_score.temporal_consistency,
                    critic_score.emotional_plausibility,
                    critic_score.persona_deviation,
                    phase3_ms / 1000,
                )
                final_diary = diary_text
                break

            logger.info(
                "[Day %d] Phase 3: Critic Evaluation ... Reject (score: %d/%d/%d) -> Retry %d/%d",
                day,
                critic_score.temporal_consistency,
                critic_score.emotional_plausibility,
                critic_score.persona_deviation,
                attempt_idx + 1,
                self._config.max_retries,
            )
            revision_instruction = critic_score.revision_instruction
            revision_instruction = _sanitize_revision(revision_instruction)
        else:
            # All retries exhausted → Best-of-N
            best = self._select_best_candidate(candidates)
            final_diary = best.diary_text
            curr_state = best.state
            fallback_used = True
            logger.warning(
                "[Day %d] Fallback: Best-of-N (score: %d)",
                day,
                best.total_score,
            )

        retry_count = max(0, len(candidates) - 1)

        expected_delta = compute_expected_delta(event, self._config.emotion_sensitivity)
        deviation = compute_deviation(prev_state, curr_state, expected_delta)
        actual_delta = {param: getattr(curr_state, param) - getattr(prev_state, param) for param in expected_delta}

        # Critic ログ蓄積
        if last_critic_result is not None:
            log_entry = CriticLogEntry(
                day=day,
                scores=last_critic_result,
                actor_input_summary=(
                    f"state={prev_state.fatigue:.2f}/{prev_state.motivation:.2f}"
                    f"/{prev_state.stress:.2f} event={event.description[:50]}"
                ),
                generated_text_hash=compute_text_hash(final_diary),
                failure_patterns=extract_failure_patterns(last_critic_result),
                llm_delta_reason=delta_reason,
                inverse_estimation_score=last_critic_result.inverse_estimation_score,
            )
            self._critic_log.add(log_entry)

        return GenerationRecord(
            day=day,
            event=event,
            initial_state=prev_state,
            final_state=curr_state,
            diary_text=final_diary,
            critic_scores=all_scores,
            retry_count=retry_count,
            fallback_used=fallback_used,
            temperature_used=candidates[-1].temperature if candidates else self._config.initial_temperature,
            phase1_duration_ms=phase1_ms,
            phase2_duration_ms=phase2_total_ms,
            phase3_duration_ms=phase3_total_ms,
            expected_delta=expected_delta,
            actual_delta=actual_delta,
            deviation=deviation,
        )

    def _create_fallback_state(
        self,
        prev_state: CharacterState,
        day: int,
        event: DailyEvent,
    ) -> CharacterState:
        """Phase 1 フォールバック: 前日の状態をコピーし暫定サマリを挿入する。

        Args:
            prev_state: 前日のキャラクター内部状態。
            day: 経過日数。
            event: 当日のイベント。

        Returns:
            フォールバック用の CharacterState。
        """
        fallback_summary = (
            f"[Day {day}: フォールバック - "
            f"イベント「{event.description[:_FALLBACK_DESCRIPTION_LENGTH]}」に対する状態更新に失敗]"
        )
        new_buffer = [*prev_state.memory_buffer, fallback_summary]
        return prev_state.model_copy(update={"memory_buffer": new_buffer})

    @staticmethod
    def _compute_prompt_hashes(prompts_dir: Path) -> dict[str, str]:
        """prompts/ ディレクトリ内の .md ファイルの SHA-256 ハッシュを計算する。"""
        hashes: dict[str, str] = {}
        if prompts_dir.exists():
            for md_file in sorted(prompts_dir.glob("*.md")):
                content = md_file.read_bytes()
                hashes[md_file.name] = hashlib.sha256(content).hexdigest()
        return hashes

    def _select_best_candidate(self, candidates: list[RetryCandidate]) -> RetryCandidate:
        """Best-of-N: 全候補から CriticScore 合計値が最大のものを選択する。

        Args:
            candidates: リトライ候補のリスト。

        Returns:
            最高スコアの候補。
        """
        return max(candidates, key=lambda c: c.total_score)
