"""
Pipeline モジュール -- 3-Phase パイプラインの実行制御。

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

from csdg.engine.constants import (
    ENDING_PATTERN_EXAMPLES,
    THEME_WORD_PER_DAY_LIMIT,
)
from csdg.engine.critic import (
    compute_deviation,
    compute_expected_delta,
    compute_trigram_overlap,
    judge,
)
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
_DEVIATION_GUARD_THRESHOLD = 0.10
_DEVIATION_GUARD_ALPHA = 0.5

# シーンを構成する場所・物のマーカー語
_SCENE_MARKERS = (
    # 場所
    "古書店",
    "電車",
    "コンビニ",
    "会議室",
    "カフェ",
    "駅",
    "図書館",
    "公園",
    # 具体物 (文具・文学)
    "万年筆",
    "インク",
    "背表紙",
    "古本",
    "栞",
    "ペン",
    "ノート",
    "手帳",
    "付箋",
    # 具体物 (日常・飲食)
    "茶碗",
    "珈琲",
    "缶コーヒー",
    "マグカップ",
    "湯気",
    # 具体物 (環境・感覚)
    "蛍光灯",
    "窓",
    "キーボード",
    "自動販売機",
    "段ボール",
    "傘",
    "夕焼け",
    # 場面
    "部屋",
)

# 書き出しパターン分類用キーワード
_OPENING_METAPHOR_KEYWORDS = ("まるで", "のような", "ように")
_OPENING_SENSORY_KEYWORDS = (
    "匂い",
    "音",
    "光",
    "温度",
    "風",
    "空気",
    "肌",
    "声",
    "冷たい",
    "暗い",
    "静か",
    "沈黙",
    "色",
    "影",
    "熱",
    "暖かい",
    "湿",
)
_OPENING_RECALL_KEYWORDS = (
    "あの頃",
    "あの日",
    "大学院",
    "昔",
    "思い出",
    "記憶",
    "かつて",
    "当時",
    "以前",
    "去年",
    "1年前",
)

# 場面構造パターンのマーカー (検出優先順: 古書店型 > 会議型 > 帰路型)
_STRUCTURE_PATTERNS: dict[str, tuple[str, ...]] = {
    "古書店型": ("古書店",),
    "会議型": ("会議室", "会議"),
    "帰路型": ("帰り道", "帰りの", "電車", "自宅", "自室"),
}

# 哲学者・思想家のマーカー
_PHILOSOPHER_MARKERS = (
    "西田幾多郎",
    "利休",
    "ハイデガー",
    "カフカ",
    "ベンヤミン",
    "メルロ=ポンティ",
    "ソクラテス",
    "プラトン",
    "ウィトゲンシュタイン",
    "野中郁次郎",
    "和辻",
    "九鬼",
    "鈴木大拙",
    "漱石",
    "太宰",
    "宮沢賢治",
    "サルトル",
    "フッサール",
    "デリダ",
)

# 余韻末尾パターン分類用キーワード
_ENDING_DAROO_KEYWORDS = ("だろう", "だろうか", "のだろう", "なのか", "ないのか")
_ENDING_KAMOSHIRENAI_KEYWORDS = ("かもしれない",)
_ENDING_INAI_KEYWORDS = ("ずにいる", "ないでいる", "ていない")
_ENDING_TEIRU_KEYWORDS = ("ている", "ていた")
_ENDING_ACTION_KEYWORDS = (
    "閉じた",
    "消した",
    "置いた",
    "立った",
    "歩いた",
    "座った",
    "開けた",
    "飲んだ",
    "落ちた",
    "捨てた",
    "入れた",
    "しまった",
)

# 主題語の追跡対象
_THEME_WORD_MARKERS = ("効率", "非効率", "最適化", "自動化")

# 修辞疑問文の抽出パターン
_RHETORICAL_PATTERN = re.compile(
    r"[^。\n]{5,30}(?:って[、,]?\s*何|とは[、,]?\s*何|って[、,]?\s*誰|"
    r"って[、,]?\s*どう|のため[？?]|に対して[？?]|"  # noqa: RUF001
    r"のだろうか|なのか[。？?、,]|ないのか[。？?、,])"  # noqa: RUF001
)
_MAX_PREV_RHETORICAL = 5


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


_OPENING_TEXT_LENGTH = 80


def _extract_opening_text(diary_text: str) -> str:
    """日記の冒頭テキスト (先頭80文字) を抽出する。

    Markdown 見出し行と空行をスキップし、実質的な本文の冒頭を返す。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        冒頭テキスト (最大80文字)。本文がない場合は空文字列。
    """
    for line in diary_text.strip().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped[:_OPENING_TEXT_LENGTH]
    return ""


def _detect_opening_pattern(diary_text: str) -> str:
    """日記の冒頭から書き出しパターンを分類する。

    Prompt_Generator.md で定義された6パターン (比喩型/五感型/会話型/問い型/断片型/回想型)
    のいずれかに分類する。判定できない場合は「その他」を返す。

    Markdown 見出し行 (``#`` で始まる行) と空行はスキップし、
    実質的な本文の冒頭行を判定対象にする。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        パターン名の文字列。
    """
    first_line = ""
    for line in diary_text.strip().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        first_line = stripped
        break
    head = first_line[:80]

    if any(kw in head for kw in _OPENING_METAPHOR_KEYWORDS):
        return "比喩型"
    if head.startswith(("\u300c", "\u300e")):  # 「 or 『
        return "会話型"
    if (
        head.endswith(("?", "\uff1f", "\u3060\u308d\u3046\u304b"))
        or re.search(r"\u3060\u308d\u3046[\u3002\s]*$", head)
        or re.search(
            r"(\u3060\u308d\u3046\u304b|\u3067\u3059\u304b|\u307e\u305b\u3093\s*\u304b)[\u3002\uff1f?\s]",
            head,
        )
    ):
        return "問い型"
    # 断片型: 句点区切りの短いフレーズが3つ以上 (五感型・回想型より優先)
    if first_line:
        fragments = [f.strip() for f in first_line.split("\u3002") if f.strip()]
        if len(fragments) >= 3 and all(len(f) <= 10 for f in fragments):
            return "断片型"
    # 会話の残響型: 人物の声・言葉が残っている表現 (五感型より優先)
    if re.search(r"(さん|くん|ちゃん|先生|先輩|後輩)の(声|言葉|一言)", head):
        return "会話型"
    if any(kw in head for kw in _OPENING_SENSORY_KEYWORDS):
        return "五感型"
    if any(kw in head for kw in _OPENING_RECALL_KEYWORDS):
        return "回想型"
    # 断片型 (フォールバック): 行が短い
    if first_line and len(first_line) < 40:
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


def _detect_structure_pattern(diary_text: str) -> str:
    """日記の場面構造パターンを分類する。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        パターン名の文字列 (帰路型/古書店型/会議型/その他)。
    """
    for pattern_name, markers in _STRUCTURE_PATTERNS.items():
        match_count = sum(1 for m in markers if m in diary_text)
        if pattern_name == "帰路型" and match_count >= 1:
            return "帰路型"
        if pattern_name != "帰路型" and match_count >= 1:
            return pattern_name
    return "その他"


def _extract_used_philosophers(diary_text: str) -> list[str]:
    """日記テキストから言及された哲学者・思想家を抽出する。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        言及された哲学者名のリスト。
    """
    return [p for p in _PHILOSOPHER_MARKERS if p in diary_text]


def _detect_ending_pattern(diary_text: str) -> str:
    """余韻の末尾構文パターンを分類する。

    末尾段落を解析し、以下の優先順位で分類する:
    「〜だろう系」「〜かもしれない系」「〜ずにいる系」「〜ている系」
    「行動締め系」「引用系」「体言止め系」「省略系」「その他」

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        パターン名の文字列。
    """
    ending = _extract_ending(diary_text)
    if not ending:
        return "その他"

    # 末尾の文を取得 (末尾2文をスキャン対象にする)
    sentences = [s.strip() for s in re.split(r"[。]", ending) if s.strip()]
    last_sentence = sentences[-1] if sentences else ending
    last_two = " ".join(sentences[-2:]) if len(sentences) >= 2 else last_sentence

    # 文法パターン (優先度高: 既存3分類 — かもしれない を だろう より先に判定)
    if any(kw in last_two for kw in _ENDING_KAMOSHIRENAI_KEYWORDS):
        return "〜かもしれない系"
    if any(kw in last_two for kw in _ENDING_DAROO_KEYWORDS):
        return "〜だろう系"
    if any(kw in last_two for kw in _ENDING_INAI_KEYWORDS):
        return "〜ずにいる系"

    # ~ている系: 末尾が「ている」「ていた」で終わる (「ていない」は上で捕捉済み)
    # 最終文だけでなく、末尾2文のいずれかの文末もチェック
    clean_last = re.sub(r"[。.…\s]+$", "", last_sentence)
    if any(clean_last.endswith(kw) for kw in _ENDING_TEIRU_KEYWORDS):
        return "〜ている系"
    if len(sentences) >= 2:
        clean_prev = re.sub(r"[。.…\s]+$", "", sentences[-2])
        if any(clean_prev.endswith(kw) for kw in _ENDING_TEIRU_KEYWORDS):
            return "〜ている系"

    # 行動締め系: 末尾に動作動詞を含む
    if any(kw in last_two for kw in _ENDING_ACTION_KEYWORDS):
        return "行動締め系"

    # 引用系: 末尾段落に「」か『』を含む
    if "「" in ending or "『" in ending:
        return "引用系"

    # 体言止め系: 末尾の文が短く (40文字以下)、漢字/カタカナ2文字以上で終わる
    if len(clean_last) <= 40 and clean_last and re.search(r"[\u4e00-\u9fff\u30a0-\u30ff]{2,}$", clean_last):
        return "体言止め系"

    # 省略系: 末尾が「......」で終わる (他パターンに該当しない場合)
    if ending.rstrip().endswith("......"):
        return "省略系"

    return "その他"


def _count_theme_words(diary_text: str) -> dict[str, int]:
    """日記テキスト中の主題語の出現回数をカウントする。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        主題語をキー、出現回数を値とする辞書。
    """
    return {word: diary_text.count(word) for word in _THEME_WORD_MARKERS}


def _extract_rhetorical_questions(
    diary_text: str,
    max_questions: int = _MAX_PREV_RHETORICAL,
) -> list[str]:
    """日記テキストから修辞疑問文を抽出する。

    「〜って、何に対して?」「〜のため?」等の問いかけパターンを検出し、
    Day 間で蓄積することで反復を防止する。

    Args:
        diary_text: 日記テキスト全文。
        max_questions: 返す修辞疑問文の最大数。

    Returns:
        抽出された修辞疑問文のリスト (各50文字以内)。
    """
    matches = _RHETORICAL_PATTERN.findall(diary_text)
    return [m.strip()[:50] for m in matches[:max_questions]]


def _detect_scene_markers(diary_text: str) -> set[str]:
    """日記テキストに出現するシーンマーカー語を検出する。

    Args:
        diary_text: 日記テキスト全文。

    Returns:
        出現したマーカー語の集合。
    """
    return {marker for marker in _SCENE_MARKERS if marker in diary_text}


def _validate_structural_constraints(
    diary_text: str,
    used_ending_patterns: list[str],
    used_structures: list[str],
    used_openings: list[str],
    theme_word_totals: dict[str, int],
    prev_openings_text: list[str] | None = None,
    prev_endings_text: list[str] | None = None,
    prev_diary_texts: list[str] | None = None,
    current_day: int = 7,
) -> list[str]:
    """生成された日記の構造的制約違反を検出する。

    Critic (Phase 3) が検査しない構造的制約を軽量にバリデーションし、
    違反時の具体的な修正指示を返す。

    Args:
        diary_text: 生成された日記テキスト。
        used_ending_patterns: 過去の余韻パターンリスト。
        used_structures: 過去の場面構造パターンリスト。
        used_openings: 過去の書き出しパターンリスト。
        theme_word_totals: 主題語の累計使用回数。
        prev_openings_text: 過去の冒頭テキストリスト (trigram 重複チェック用)。
        prev_endings_text: 過去の余韻テキストリスト (trigram 重複チェック用)。
        prev_diary_texts: 過去の日記テキストリスト (フレーズ重複チェック用)。
        current_day: 現在のDay番号 (1-7)。Day 1-5 はパターン上限を厳格化する。

    Returns:
        違反メッセージのリスト。空の場合は制約をすべて満たしている。
    """
    violations: list[str] = []

    # 1. 余韻パターン上限チェック (2回まで)
    ending_pattern = _detect_ending_pattern(diary_text)
    ep_counts: dict[str, int] = {}
    for p in used_ending_patterns:
        if ": " in p:
            name = p.split(": ", 1)[1]
            ep_counts[name] = ep_counts.get(name, 0) + 1
    ep_limit = 1 if current_day <= 5 else 2
    if ending_pattern != "その他" and ep_counts.get(ending_pattern, 0) >= ep_limit:
        available = [n for n in ENDING_PATTERN_EXAMPLES if ep_counts.get(n, 0) < ep_limit and n != ending_pattern]
        alt = f" 代わりに{'か'.join(available[:3])}を使ってください。" if available else ""
        violations.append(f"余韻が「{ending_pattern}」ですが既に{ep_limit}回使用済みです。{alt}")

    # 2. 場面構造の連続使用チェック
    structure = _detect_structure_pattern(diary_text)
    if used_structures:
        last = used_structures[-1]
        prev_structure = last.split(": ", 1)[1] if ": " in last else ""
        if structure == prev_structure and structure != "その他":
            violations.append(f"場面構造が前日と同じ「{structure}」です。異なる構造に変更してください。")

    # 3. 場面構造の上限チェック
    st_counts: dict[str, int] = {}
    for s in used_structures:
        if ": " in s:
            name = s.split(": ", 1)[1]
            st_counts[name] = st_counts.get(name, 0) + 1
    pattern_limits = {"古書店型": 2, "帰路型": 2}
    st_limit = pattern_limits.get(structure, 3)
    if structure != "その他" and st_counts.get(structure, 0) >= st_limit:
        violations.append(f"「{structure}」は既に{st_counts[structure]}回使用され上限({st_limit}回)到達です。")

    # 4. 主題語の per-day 上限チェック
    day_counts = _count_theme_words(diary_text)
    for word, count in day_counts.items():
        if count > THEME_WORD_PER_DAY_LIMIT:
            violations.append(
                f"「{word}」が{count}回使用 (上限{THEME_WORD_PER_DAY_LIMIT}回/日)。代替表現に言い換えてください。"
            )

    # 5. 書き出しパターン上限チェック
    opening = _detect_opening_pattern(diary_text)
    op_counts: dict[str, int] = {}
    for o in used_openings:
        if ": " in o:
            name = o.split(": ", 1)[1]
            op_counts[name] = op_counts.get(name, 0) + 1
    op_limit = 1 if current_day <= 5 else 2
    if opening != "その他" and op_counts.get(opening, 0) >= op_limit:
        violations.append(
            f"書き出し「{opening}」は既に{op_counts[opening]}回使用 (上限{op_limit}回)。別パターンにしてください。"
        )

    # 6. 冒頭テキストの Day 間 trigram 重複チェック
    if prev_openings_text:
        opening_text = _extract_opening_text(diary_text)
        if opening_text:
            for i, prev_text in enumerate(prev_openings_text):
                overlap = compute_trigram_overlap(opening_text, prev_text)
                if overlap > 0.5:
                    violations.append(
                        f"冒頭テキストが Day {i + 1} と類似しすぎ (trigram overlap {overlap:.0%})。"
                        "全く異なる書き出しにしてください。"
                    )
                    break

    # 7. 余韻テキストの Day 間 trigram 重複チェック
    if prev_endings_text:
        curr_ending = _extract_ending(diary_text)
        if curr_ending:
            for i, prev_text in enumerate(prev_endings_text):
                overlap = compute_trigram_overlap(curr_ending, prev_text)
                if overlap > 0.5:
                    violations.append(
                        f"余韻テキストが Day {i + 1} と類似しすぎ (trigram overlap {overlap:.0%})。"
                        "全く異なる余韻にしてください。"
                    )
                    break

    # 8. 禁止余韻パターンの独立チェック (前日データ不要)
    ending = _extract_ending(diary_text)
    if ending:
        _forbidden_ending_phrases = (
            "本当に両立",
            "の間にある溝",
            "本当に分離できる",
        )
        for phrase in _forbidden_ending_phrases:
            if phrase in ending:
                violations.append(
                    f"禁止余韻パターン「{phrase}」が使用されています。"
                    " Prompt_Generator.md の禁止リストに記載されたパターンは使用できません。"
                )

    # 9. 本文フレーズの Day 間重複チェック (15文字以上の完全一致)
    if prev_diary_texts:
        curr_sentences = [s.strip() for s in re.split(r"[。\n]", diary_text) if len(s.strip()) >= 15]
        found_dup = False
        for prev_text in prev_diary_texts:
            if found_dup:
                break
            for sent in curr_sentences:
                # 括弧内の独白 (読者語りかけ) は除外
                if sent.startswith("\uff08") or sent.startswith("("):
                    continue
                phrase = sent[:15]
                if phrase in prev_text:
                    violations.append(
                        f"フレーズ「{phrase}」が過去の日記と重複しています。 異なる表現に言い換えてください。"
                    )
                    found_dup = True
                    break

    # 10. 文字数の理想範囲チェック (タイトル行除外)
    body_lines = [line for line in diary_text.strip().split("\n") if not re.match(r"^#{1,6}\s", line)]
    body_len = len("\n".join(body_lines).strip())
    if body_len > 450:
        over = body_len - 420
        violations.append(f"本文が{body_len}文字です。約420文字 (450文字以下) に削減してください (現在{over}文字超過)")

    # 11. 末尾フックの弱さチェック (Day 1-6 のみ)
    if current_day <= 6:
        ending = _extract_ending(diary_text)
        if ending:
            ending_sentences = [s.strip() for s in re.split(r"[。]", ending) if s.strip()]
            last_sentence = ending_sentences[-1] if ending_sentences else ""
            clean_last = re.sub(r"[。.…\s]+$", "", last_sentence)

            # Day2型: 弱い修辞疑問 (「〜だろう」等で終わり、具体的な人物への言及がない場合)
            weak_rhetorical_endings = ("だろう", "だろうか", "のだろう", "のだろうか")
            if any(clean_last.endswith(kw) for kw in weak_rhetorical_endings):
                has_specific_subject = any(name in last_sentence for name in ("那由他", "ミナ", "店主"))
                if not has_specific_subject:
                    violations.append(
                        "末尾が弱い修辞疑問 (「〜だろう」) で閉じています。"
                        "具体的な人物・出来事に紐づいた疑問か、"
                        "別の種類のフック (予告的行動・未回収の出来事等) に変更してください。"
                    )

            # Day6型: 感情の結論で閉じている
            emotional_conclusion_markers = (
                "心地よい",
                "安心した",
                "嬉しい",
                "嬉しかった",
                "不安だ",
                "寂しい",
                "悲しい",
                "楽になった",
                "すっきりした",
                "ほっとした",
                "満足",
                "納得",
            )
            if any(marker in clean_last for marker in emotional_conclusion_markers):
                violations.append(
                    "末尾が感情の結論 (「心地よい」等) で閉じています。"
                    "フックは文章を「開く」ものです。感情で閉じず、"
                    "未解決の違和感や予告的行動で終えてください。"
                )

    return violations


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
    structural_violation_count: int = 0


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
        used_structures: list[str] = []
        used_philosophers: dict[str, int] = {}
        used_ending_patterns: list[str] = []
        theme_word_totals: dict[str, int] = {}
        prev_rhetorical: list[str] = []
        scene_marker_days: dict[str, int] = {}
        prev_openings_text: list[str] = []
        prev_endings_text: list[str] = []
        prev_diary_texts: list[str] = []
        prev_day_ending_text: str = ""

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
                        used_structures=list(used_structures),
                        used_philosophers=dict(used_philosophers),
                        used_ending_patterns=list(used_ending_patterns),
                        theme_word_totals=dict(theme_word_totals),
                        prev_rhetorical=list(prev_rhetorical),
                        scene_marker_days=dict(scene_marker_days),
                        prev_openings_text=list(prev_openings_text),
                        prev_endings_text=list(prev_endings_text),
                        prev_diary_texts=list(prev_diary_texts),
                        prev_day_ending=prev_day_ending_text,
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
                    # 冒頭テキストの蓄積 (テキストレベル重複検出用)
                    opening_text = _extract_opening_text(record.diary_text)
                    if opening_text:
                        prev_openings_text.append(opening_text)
                    # 余韻テキストの蓄積 (テキストレベル重複検出用)
                    ending_text = _extract_ending(record.diary_text)
                    if ending_text:
                        prev_endings_text.append(ending_text)
                    # 日記本文の蓄積 (フレーズ重複チェック用)
                    prev_diary_texts.append(record.diary_text)
                    # 前日末尾テキストの更新 (次のDayの前日接続用)
                    prev_day_ending_text = _extract_ending(record.diary_text)
                    # 場面構造パターンの蓄積
                    structure = _detect_structure_pattern(record.diary_text)
                    used_structures.append(f"Day {day}: {structure}")
                    # 哲学者引用の蓄積
                    for phil in _extract_used_philosophers(record.diary_text):
                        used_philosophers[phil] = used_philosophers.get(phil, 0) + 1
                    # 余韻構文パターンの蓄積
                    ending_pattern = _detect_ending_pattern(record.diary_text)
                    used_ending_patterns.append(f"Day {day}: {ending_pattern}")
                    # 主題語の累計カウント
                    day_counts = _count_theme_words(record.diary_text)
                    for word, count in day_counts.items():
                        theme_word_totals[word] = theme_word_totals.get(word, 0) + count
                    # 修辞疑問文の蓄積
                    new_rhetoricals = _extract_rhetorical_questions(record.diary_text)
                    prev_rhetorical.extend(new_rhetoricals)
                    prev_rhetorical = prev_rhetorical[-_MAX_PREV_RHETORICAL:]
                    # シーンマーカーの出現日数を更新
                    day_markers = _detect_scene_markers(record.diary_text)
                    for marker in day_markers:
                        scene_marker_days[marker] = scene_marker_days.get(marker, 0) + 1
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
        used_structures: list[str] | None = None,
        used_philosophers: dict[str, int] | None = None,
        used_ending_patterns: list[str] | None = None,
        theme_word_totals: dict[str, int] | None = None,
        prev_rhetorical: list[str] | None = None,
        scene_marker_days: dict[str, int] | None = None,
        prev_openings_text: list[str] | None = None,
        prev_endings_text: list[str] | None = None,
        prev_diary_texts: list[str] | None = None,
        prev_day_ending: str = "",
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
            used_structures: 過去の日記で使用された場面構造パターン (反復回避用)。
            used_philosophers: 哲学者・思想家の使用回数辞書 (反復回避用)。
            used_ending_patterns: 過去の日記で使用された余韻構文パターン (反復回避用)。
            theme_word_totals: 主題語の累計使用回数 (頻度制限用)。
            prev_rhetorical: 過去の日記で使用された修辞疑問文 (反復回避用)。
            scene_marker_days: シーンマーカーの出現日数 (反復回避用)。
            prev_openings_text: 過去の冒頭テキストリスト (テキスト重複検出用)。
            prev_endings_text: 過去の余韻テキストリスト (テキスト重複検出用)。
            prev_day_ending: 前日の日記の末尾段落テキスト (前日接続用)。

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

        # --- Phase 1.5: Deviation Guard ---
        # Phase 1 の出力 deviation が大きい場合、Phase 2/3 リトライでは修正不能なため
        # ここでソフト補正を適用する (a=0.5 で expected_delta 方向にブレンド)
        if not fallback_used and curr_state is not None:
            expected_delta = compute_expected_delta(event, self._config.emotion_sensitivity)
            deviation = compute_deviation(prev_state, curr_state, expected_delta)
            max_dev = max(abs(v) for v in deviation.values()) if deviation else 0.0
            if max_dev > _DEVIATION_GUARD_THRESHOLD:
                alpha = _DEVIATION_GUARD_ALPHA
                updates: dict[str, float] = {}
                for param in ("stress", "motivation", "fatigue"):
                    actual = getattr(curr_state, param)
                    expected_val = getattr(prev_state, param) + expected_delta.get(param, 0.0)
                    corrected = actual * (1.0 - alpha) + expected_val * alpha
                    # fatigue: 0.0-1.0, stress/motivation: -1.0-1.0
                    lo = 0.0 if param == "fatigue" else -1.0
                    hi = 1.0
                    updates[param] = max(lo, min(hi, corrected))
                curr_state = curr_state.model_copy(update=updates)
                new_dev = compute_deviation(prev_state, curr_state, expected_delta)
                new_max = max(abs(v) for v in new_dev.values()) if new_dev else 0.0
                logger.info(
                    "[Day %d] Deviation Guard: max_dev %.3f -> %.3f (alpha=%.1f)",
                    day,
                    max_dev,
                    new_max,
                    alpha,
                )

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

        is_high_impact = abs(event.emotional_impact) > 0.7
        structural_retry_used = False
        pending_structural_violations: list[str] | None = None
        attempt_idx = 0

        while attempt_idx < self._config.max_retries:
            temperature = schedule[attempt_idx] if attempt_idx < len(schedule) else schedule[-1]

            # 高インパクト日で persona_deviation が低い場合、初回リトライのみ温度を維持
            if is_high_impact and len(candidates) == 1 and candidates[-1].critic_score.persona_deviation < 3:
                temperature = max(temperature, self._config.initial_temperature)

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
                used_structures=used_structures,
                used_philosophers=used_philosophers,
                used_ending_patterns=used_ending_patterns,
                theme_word_totals=theme_word_totals,
                prev_rhetorical=prev_rhetorical,
                scene_marker_days=scene_marker_days,
                prev_openings_text=prev_openings_text,
                prev_endings_text=prev_endings_text,
                prev_day_ending=prev_day_ending,
                structural_violations=pending_structural_violations,
            )
            pending_structural_violations = None
            phase2_ms = int((time.monotonic() - phase2_start) * 1000)
            phase2_total_ms += phase2_ms
            logger.info("[Day %d] Phase 2: Content Generation ... OK (%.1fs)", day, phase2_ms / 1000)

            # 構造的制約バリデーション (Critic 前の軽量チェック)
            structural_violations = _validate_structural_constraints(
                diary_text,
                used_ending_patterns or [],
                used_structures or [],
                used_openings or [],
                theme_word_totals or {},
                prev_openings_text=prev_openings_text,
                prev_endings_text=prev_endings_text,
                prev_diary_texts=prev_diary_texts,
                current_day=day,
            )
            if structural_violations:
                logger.warning(
                    "[Day %d] 構造的制約違反 %d件: %s",
                    day,
                    len(structural_violations),
                    "; ".join(structural_violations),
                )

            # Phase 3: Critic Evaluation (3層詳細結果を取得)
            phase3_start = time.monotonic()
            critic_result = await self._critic.evaluate_full(
                prev_state,
                curr_state,
                diary_text,
                event,
                prev_diary=prev_diary,
                prev_day_ending=prev_day_ending,
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
                structural_violation_count=len(structural_violations),
            )
            candidates.append(candidate)

            if judge(critic_score):
                # 構造的制約違反がある場合、ボーナス1回再試行 (リトライ予算を消費しない)
                if structural_violations and not structural_retry_used:
                    structural_retry_used = True
                    pending_structural_violations = structural_violations
                    violation_text = "\n".join(f"- {v}" for v in structural_violations)
                    # フック関連違反には具体的な修正例を付与
                    hook_guidance = ""
                    if any("修辞疑問" in v or "感情の結論" in v for v in structural_violations):
                        hook_guidance = (
                            "\n\n【フック修正の具体例】"
                            "\nNG: 「〜だろう」「〜のだろうか」(弱い修辞疑問)"
                            "\nNG: 「心地よい」「安心した」(感情の結論)"
                            "\n○ 「明日、那由他さんにもう一度聞いてみよう。」(予告的行動)"
                            "\n○ 「あの棚の奥に見えた背表紙が、まだ気になっている。」(未回収の出来事)"
                            "\n○ 「でも、あの時の沈黙には、まだ何か隠れている。」(未解決の違和感)"
                        )
                    revision_instruction = _sanitize_revision(f"構造的制約違反:\n{violation_text}{hook_guidance}")
                    logger.info(
                        "[Day %d] Critic Pass (score: %d/%d/%d) + %d violation(s) -> ボーナス再試行",
                        day,
                        critic_score.temporal_consistency,
                        critic_score.emotional_plausibility,
                        critic_score.persona_deviation,
                        len(structural_violations),
                    )
                    # attempt_idx を進めない (ボーナス再試行)
                    continue

                if structural_violations:
                    logger.info(
                        "[Day %d] Phase 3: Critic Pass (score: %d/%d/%d) with %d warning(s) (%.1fs)",
                        day,
                        critic_score.temporal_consistency,
                        critic_score.emotional_plausibility,
                        critic_score.persona_deviation,
                        len(structural_violations),
                        phase3_ms / 1000,
                    )
                else:
                    logger.info(
                        "[Day %d] Phase 3: Critic Evaluation ... Pass (score: %d/%d/%d) (%.1fs)",
                        day,
                        critic_score.temporal_consistency,
                        critic_score.emotional_plausibility,
                        critic_score.persona_deviation,
                        phase3_ms / 1000,
                    )
                # Best-of-N: 複数候補がある場合は最良候補を選択
                # (構造的制約のボーナス再試行で last-write-wins になっていた問題の修正)
                if len(candidates) > 1:
                    best = self._select_best_candidate(candidates)
                    if best.attempt != candidate.attempt:
                        logger.info(
                            "[Day %d] Best-of-N: candidate %d (total=%d, viol=%d) "
                            "selected over latest candidate %d (total=%d, viol=%d)",
                            day,
                            best.attempt,
                            best.total_score,
                            best.structural_violation_count,
                            candidate.attempt,
                            candidate.total_score,
                            candidate.structural_violation_count,
                        )
                    final_diary = best.diary_text
                    curr_state = best.state
                else:
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
            # Critic のリビジョン指示と構造違反フィードバックを合流
            revision_parts: list[str] = []
            if critic_score.revision_instruction:
                revision_parts.append(critic_score.revision_instruction)
            if structural_violations:
                violation_text = "\n".join(f"- {v}" for v in structural_violations)
                revision_parts.append(f"構造的制約違反:\n{violation_text}")
            revision_instruction = _sanitize_revision(
                "\n\n".join(revision_parts) if revision_parts else None,
            )
            attempt_idx += 1
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
        """Best-of-N: 全候補からスコアが最大のものを選択する。

        構造的制約違反がある候補にはペナルティ (-1/violation) を適用し、
        違反のない候補を優先する。

        Args:
            candidates: リトライ候補のリスト。

        Returns:
            最高スコアの候補。
        """
        return max(candidates, key=lambda c: c.total_score - c.structural_violation_count)
