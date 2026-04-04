"""
Critic モジュール -- Phase 3 (Critic評価) を担当する。

3層構造 (RuleBasedValidator / StatisticalChecker / LLMJudge) による
評価パイプラインを実装する。各層は独立にスコアを算出し、
重み付き加重平均で最終 CriticScore を生成する。

architecture.md §3.3 に準拠する。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from csdg.engine.prompt_loader import load_prompt
from csdg.schemas import (
    CharacterState,
    CriticResult,
    CriticScore,
    DailyEvent,
    LayerScore,
)

if TYPE_CHECKING:
    from csdg.config import CSDGConfig
    from csdg.engine.llm_client import LLMClient

logger = logging.getLogger(__name__)

_DEFAULT_PROMPTS_DIR = Path("prompts")

_SCORE_FIELDS = ("temporal_consistency", "emotional_plausibility", "persona_deviation")

_CONTINUOUS_PARAMS = ("fatigue", "motivation", "stress")

# RuleBasedValidator の定数 (ブログ記事: 約400文字ベース)
_MIN_DIARY_LENGTH = 300
_MAX_DIARY_LENGTH = 500
_IDEAL_MIN_LENGTH = 350
_IDEAL_MAX_LENGTH = 450
_MAX_TRIGRAM_OVERLAP = 0.30
_BASE_SCORE = 2.5
_EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
    r"\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
    r"\U00002600-\U000026FF]",
)

# Veto 権 (致命的違反) の定数
_CRITICAL_CHAR_DEVIATION = 0.5  # 文字数レンジの±50%逸脱
_CRITICAL_TRIGRAM_OVERLAP = 0.50  # trigram overlap > 50%
_CONSENSUS_AMPLIFICATION = 0.5  # L1/L2 コンセンサス補正の増幅係数
_MAX_SCORE_ADJUSTMENT = 0  # コンセンサス補正の安全上限 (±0: 純粋加重平均 round に従う)
_FORBIDDEN_PRONOUNS = ("俺", "僕", "私", "あたし", "おれ", "ぼく", "あたくし", "わし", "うち")

# 余韻テンプレート反復検出用マーカー
_ENDING_TEMPLATE_MARKERS = ("間にある", "両立", "分離", "の溝")

# StatisticalChecker の定数
_MIN_AVG_SENTENCE_LENGTH = 10
_MAX_AVG_SENTENCE_LENGTH = 80
_MAX_DEVIATION_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# 定量検証関数 (LLM に依存しない純粋関数) -- 既存 API 維持
# ---------------------------------------------------------------------------


def compute_expected_delta(
    event: DailyEvent,
    sensitivity: dict[str, float],
) -> dict[str, float]:
    """イベントの emotional_impact から各パラメータの期待変動幅を算出する。

    Args:
        event: 当日のイベント定義。
        sensitivity: 感情感度係数 (例: {"stress": -0.3, "motivation": 0.4, "fatigue": -0.2})。

    Returns:
        各パラメータの期待変動幅。
        例: impact=0.6, sensitivity={"stress": -0.3} -> {"stress": -0.18}
    """
    return {param: event.emotional_impact * coeff for param, coeff in sensitivity.items()}


def compute_deviation(
    prev_state: CharacterState,
    curr_state: CharacterState,
    expected_delta: dict[str, float],
) -> dict[str, float]:
    """実際の変動と期待変動の乖離を算出する。

    actual_delta = curr.param - prev.param
    deviation = actual_delta - expected_delta

    Args:
        prev_state: 前日のキャラクター内部状態 (h_{t-1})。
        curr_state: 今日のキャラクター内部状態 (h_t)。
        expected_delta: compute_expected_delta() の出力。

    Returns:
        各パラメータの乖離値。
    """
    return {
        param: (getattr(curr_state, param) - getattr(prev_state, param)) - expected_val
        for param, expected_val in expected_delta.items()
    }


def judge(score: CriticScore) -> bool:
    """全スコアが 3 以上で True (Pass)。1つでも 3 未満で False (Reject)。

    Args:
        score: Critic が出力した評価スコア。

    Returns:
        Pass なら True、Reject なら False。
    """
    return all(getattr(score, field) >= 3 for field in _SCORE_FIELDS)


# ---------------------------------------------------------------------------
# Layer 1: RuleBasedValidator (決定論的)
# ---------------------------------------------------------------------------


def extract_trigrams(text: str) -> set[str]:
    """テキストからトライグラムの集合を抽出する。"""
    chars = text.replace(" ", "").replace("\n", "")
    if len(chars) < 3:
        return set()
    return {chars[i : i + 3] for i in range(len(chars) - 2)}


def compute_trigram_overlap(text_a: str, text_b: str) -> float:
    """2つのテキスト間のトライグラム重複率を算出する。"""
    trigrams_a = extract_trigrams(text_a)
    trigrams_b = extract_trigrams(text_b)
    if not trigrams_a or not trigrams_b:
        return 0.0
    intersection = trigrams_a & trigrams_b
    return len(intersection) / min(len(trigrams_a), len(trigrams_b))


class RuleBasedValidator:
    """Layer 1: 決定論的なルールベース検証。

    文字数レンジチェック、禁止表現の検出、前日との重複率チェック、
    感情パラメータの数値整合性を検証する。
    """

    def evaluate(
        self,
        diary_text: str,
        prev_state: CharacterState,
        curr_state: CharacterState,
        event: DailyEvent,
        expected_delta: dict[str, float],
        prev_diary: str | None = None,
    ) -> LayerScore:
        """ルールベース検証を実行する。

        Args:
            diary_text: 評価対象の日記テキスト。
            prev_state: 前日の状態。
            curr_state: 今日の状態。
            event: 当日のイベント。
            expected_delta: 期待変動幅。
            prev_diary: 前日の日記テキスト (重複チェック用)。

        Returns:
            LayerScore (各軸 1.0-5.0)。
        """
        base_scores: dict[str, float] = {
            "temporal_consistency": _BASE_SCORE,
            "emotional_plausibility": _BASE_SCORE,
            "persona_deviation": _BASE_SCORE,
        }
        penalties: dict[str, float] = {
            "temporal_consistency": 0.0,
            "emotional_plausibility": 0.0,
            "persona_deviation": 0.0,
        }
        details: dict[str, object] = {}

        # 文字数レンジチェック -> persona_deviation に影響
        # Markdown 見出し行 (# で始まる行) を除外して本文の文字数をカウント
        lines = diary_text.strip().split("\n")
        body_lines = [line for line in lines if not re.match(r"^#{1,6}\s", line)]
        body_text = "\n".join(body_lines).strip()
        char_count = len(body_text)
        details["char_count"] = char_count
        if char_count < _MIN_DIARY_LENGTH:
            penalties["persona_deviation"] += 1.5
            details["char_count_violation"] = "too_short"
        elif char_count > _MAX_DIARY_LENGTH:
            over = char_count - _MAX_DIARY_LENGTH
            if over > 80:
                penalties["persona_deviation"] += 2.0
            elif over > 40:
                penalties["persona_deviation"] += 1.5
            else:
                penalties["persona_deviation"] += 1.0
            details["char_count_violation"] = "too_long"
            details["char_count_over"] = over
        elif char_count > _IDEAL_MAX_LENGTH:
            # 理想上限(450)超〜許容上限(500)以下: 軽微ペナルティ
            penalties["persona_deviation"] += 0.5
            details["char_count_warning"] = True

        # 加点: 文字数が理想範囲内 (段階化)
        char_count_ideal = _IDEAL_MIN_LENGTH <= char_count <= _IDEAL_MAX_LENGTH
        details["char_count_ideal"] = char_count_ideal
        if 370 <= char_count <= 430:
            base_scores["temporal_consistency"] += 1.0  # sweet spot
        elif char_count_ideal:
            base_scores["temporal_consistency"] += 0.5  # acceptable

        # 禁止表現検出 (絵文字) -> persona_deviation
        emoji_matches = _EMOJI_PATTERN.findall(diary_text)
        if emoji_matches:
            penalties["persona_deviation"] += 2.0
            details["emoji_count"] = len(emoji_matches)

        # 禁止一人称検出 -> persona_deviation (veto 対象)
        found_pronouns: list[str] = []
        for pronoun in _FORBIDDEN_PRONOUNS:
            if pronoun in diary_text:
                found_pronouns.append(pronoun)
        if found_pronouns:
            penalties["persona_deviation"] += 2.0
            details["forbidden_pronoun_found"] = True
            details["forbidden_pronouns"] = found_pronouns

        # 加点/減点: 「わたし」の使用頻度 (段階化)
        watashi_count = diary_text.count("わたし")
        details["watashi_count"] = watashi_count
        if 4 <= watashi_count <= 6:
            base_scores["persona_deviation"] += 1.0  # sweet spot
        elif 2 <= watashi_count <= 8:
            base_scores["persona_deviation"] += 0.5  # acceptable
        elif watashi_count > 8:
            base_scores["persona_deviation"] -= 1.0  # overuse penalty

        # 加点: 「......」の使用頻度 (段階化)
        ellipsis_count = diary_text.count("......")
        details["ellipsis_count"] = ellipsis_count
        if 2 <= ellipsis_count <= 3:
            base_scores["persona_deviation"] += 1.0  # sweet spot
        elif ellipsis_count in (1, 4):
            base_scores["persona_deviation"] += 0.5  # acceptable

        # 前日との重複率チェック -> temporal_consistency
        if prev_diary:
            overlap = compute_trigram_overlap(diary_text, prev_diary)
            details["trigram_overlap"] = round(overlap, 3)
            if overlap > _MAX_TRIGRAM_OVERLAP:
                penalties["temporal_consistency"] += 1.5
                details["overlap_violation"] = True
            elif overlap < 0.10:
                # 加点: 前日との重複率が非常に低い
                base_scores["temporal_consistency"] += 1.0  # very different
            elif overlap < 0.15:
                # 加点: 前日との重複率が低い
                base_scores["temporal_consistency"] += 0.5  # moderately different

        # 感情パラメータの数値整合性 -> emotional_plausibility
        max_dev = 0.0
        for param in _CONTINUOUS_PARAMS:
            actual_delta = getattr(curr_state, param) - getattr(prev_state, param)
            expected = expected_delta.get(param, 0.0)
            dev = abs(actual_delta - expected)
            if dev > max_dev:
                max_dev = dev
            # event_impact の符号と actual_delta の方向が矛盾していないか
            if (
                abs(event.emotional_impact) > 0.5
                and expected != 0.0
                and actual_delta != 0.0
                and ((expected > 0 and actual_delta < -0.3) or (expected < 0 and actual_delta > 0.3))
            ):
                penalties["emotional_plausibility"] += 1.0
                details[f"{param}_direction_mismatch"] = True

        # 加点/減点: 感情パラメータの乖離に基づく段階スケーリング
        # Deviation Guard (alpha=0.5) 後の実測値は 0.05-0.07 に収束するため、
        # その範囲で十分な加点が得られるよう閾値を調整
        details["rule_max_deviation"] = round(max_dev, 3)
        if max_dev < 0.05:
            base_scores["emotional_plausibility"] += 1.5
        elif max_dev < 0.08:
            base_scores["emotional_plausibility"] += 1.0
        elif max_dev < 0.12:
            base_scores["emotional_plausibility"] += 0.5
        elif max_dev < 0.15:
            base_scores["emotional_plausibility"] += 0.25
        elif max_dev < 0.20:
            pass  # 標準: base のまま
        else:
            base_scores["emotional_plausibility"] -= 0.5  # penalty (緩和)

        # unresolved_issue の null チェック: 強いネガティブイベントなのに未解決課題が未設定
        if event.emotional_impact <= -0.5 and curr_state.unresolved_issue is None:
            penalties["emotional_plausibility"] += 1.0
            details["unresolved_issue_missing"] = True

        # 余韻の構造反復チェック
        if prev_diary:
            curr_ending = self._extract_ending(diary_text)
            prev_ending = self._extract_ending(prev_diary)
            curr_has_template = any(m in curr_ending for m in _ENDING_TEMPLATE_MARKERS)
            prev_has_template = any(m in prev_ending for m in _ENDING_TEMPLATE_MARKERS)
            if curr_has_template and prev_has_template:
                penalties["temporal_consistency"] += 1.0
                details["ending_template_repetition"] = True

            # 余韻の trigram 類似度チェック (keyword 検出の補完)
            ending_overlap = compute_trigram_overlap(curr_ending, prev_ending)
            details["ending_trigram_overlap"] = round(ending_overlap, 3)
            if ending_overlap > 0.25:
                penalties["temporal_consistency"] += 1.0
                details["ending_similarity_high"] = True

        def _clamp(field: str) -> float:
            return max(1.0, min(5.0, base_scores[field] - penalties[field]))

        return LayerScore(
            temporal_consistency=_clamp("temporal_consistency"),
            emotional_plausibility=_clamp("emotional_plausibility"),
            persona_deviation=_clamp("persona_deviation"),
            details=details,
        )

    @staticmethod
    def _extract_ending(text: str) -> str:
        """末尾段落を抽出する。"""
        paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
        return paragraphs[-1] if paragraphs else ""

    def has_critical_failure(self, result: LayerScore) -> dict[str, bool]:
        """致命的違反を検出し、veto 対象軸を返す。

        致命的違反の定義:
        - 禁止一人称の使用 → persona 軸に veto
        - 文字数レンジ逸脱 (±50%超) → 全軸に veto
        - trigram overlap > 50% → temporal 軸に veto

        Args:
            result: evaluate() の戻り値 (LayerScore)。

        Returns:
            各軸の veto フラグ辞書。True = veto 発動。
        """
        veto: dict[str, bool] = {
            "temporal_consistency": False,
            "emotional_plausibility": False,
            "persona_deviation": False,
        }

        details = result.details

        # 禁止一人称 → persona 軸に veto
        if details.get("forbidden_pronoun_found"):
            veto["persona_deviation"] = True

        # 文字数レンジ逸脱 (±50%超) → 全軸に veto
        char_count = details.get("char_count", 0)
        if isinstance(char_count, int):
            mid = (_MIN_DIARY_LENGTH + _MAX_DIARY_LENGTH) / 2
            lower = mid * (1 - _CRITICAL_CHAR_DEVIATION)
            upper = _MAX_DIARY_LENGTH + 50  # 550文字超で veto
            if char_count < lower or char_count > upper:
                veto["temporal_consistency"] = True
                veto["emotional_plausibility"] = True
                veto["persona_deviation"] = True

        # trigram overlap > 50% → temporal 軸に veto
        overlap = details.get("trigram_overlap")
        if isinstance(overlap, (int, float)) and overlap > _CRITICAL_TRIGRAM_OVERLAP:
            veto["temporal_consistency"] = True

        return veto


# ---------------------------------------------------------------------------
# Layer 2: StatisticalChecker (数値的)
# ---------------------------------------------------------------------------


class StatisticalChecker:
    """Layer 2: 文体統計に基づく数値的検証。

    平均文長、句読点頻度、疑問文比率、deviation 分析を行う。
    """

    def evaluate(
        self,
        diary_text: str,
        prev_state: CharacterState,
        curr_state: CharacterState,
        event: DailyEvent,
        expected_delta: dict[str, float],
        deviation: dict[str, float],
    ) -> LayerScore:
        """統計的検証を実行する。

        Args:
            diary_text: 評価対象の日記テキスト。
            prev_state: 前日の状態。
            curr_state: 今日の状態。
            event: 当日のイベント。
            expected_delta: 期待変動幅。
            deviation: 期待変動との乖離。

        Returns:
            LayerScore (各軸 1.0-5.0)。
        """
        base_scores: dict[str, float] = {
            "temporal_consistency": _BASE_SCORE,
            "emotional_plausibility": _BASE_SCORE,
            "persona_deviation": _BASE_SCORE,
        }
        penalties: dict[str, float] = {
            "temporal_consistency": 0.0,
            "emotional_plausibility": 0.0,
            "persona_deviation": 0.0,
        }
        details: dict[str, object] = {}

        # 文体統計: 平均文長
        sentences = [s.strip() for s in re.split(r"[。.!!\n]", diary_text) if s.strip()]
        avg_sentence_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
        details["avg_sentence_length"] = round(avg_sentence_len, 1)
        details["sentence_count"] = len(sentences)

        if avg_sentence_len < _MIN_AVG_SENTENCE_LENGTH:
            penalties["persona_deviation"] += 1.0
        elif avg_sentence_len > _MAX_AVG_SENTENCE_LENGTH:
            penalties["persona_deviation"] += 0.5

        # 加点: 平均文長が適度な範囲 (段階化)
        if 25 <= avg_sentence_len <= 30:
            base_scores["persona_deviation"] += 1.0  # sweet spot
        elif 20 <= avg_sentence_len <= 35:
            base_scores["persona_deviation"] += 0.5  # acceptable

        # 句読点頻度
        punctuation_count = diary_text.count("、") + diary_text.count("。") + diary_text.count("......")
        punct_ratio = punctuation_count / max(len(diary_text), 1)
        details["punctuation_ratio"] = round(punct_ratio, 4)

        # 加点: 句読点頻度が安定範囲 (段階化)
        if 0.070 <= punct_ratio <= 0.080:
            base_scores["temporal_consistency"] += 1.0  # sweet spot
        elif 0.060 <= punct_ratio <= 0.090:
            base_scores["temporal_consistency"] += 0.5  # acceptable

        # 加点: 文数が適度な範囲 (段階化)
        sentence_count = len(sentences)
        if 35 <= sentence_count <= 45:
            base_scores["temporal_consistency"] += 1.0  # sweet spot
        elif 30 <= sentence_count <= 50:
            base_scores["temporal_consistency"] += 0.5  # acceptable

        # 疑問文比率
        question_count = diary_text.count("?") + diary_text.count("\uff1f")
        question_ratio = question_count / max(len(sentences), 1)
        details["question_ratio"] = round(question_ratio, 3)

        # 加点: 疑問文比率がとこみらしい範囲 (段階化)
        if 0.06 <= question_ratio <= 0.10:
            base_scores["persona_deviation"] += 1.0  # sweet spot
        elif 0.05 <= question_ratio <= 0.15:
            base_scores["persona_deviation"] += 0.5  # acceptable

        # deviation 分析 -> emotional_plausibility (連続スケーリング)
        # Deviation Guard 後の実測値に合わせた閾値調整
        max_deviation = max(abs(v) for v in deviation.values()) if deviation else 0.0
        details["max_deviation"] = round(max_deviation, 3)
        if max_deviation < 0.08:
            base_scores["emotional_plausibility"] += 1.5
        elif max_deviation < 0.12:
            base_scores["emotional_plausibility"] += 1.0
        elif max_deviation < 0.18:
            base_scores["emotional_plausibility"] += 0.5
        elif max_deviation < 0.30:
            pass  # base のまま
        elif max_deviation < 0.40:
            penalties["emotional_plausibility"] += 0.5  # penalty (緩和)
        elif max_deviation < 0.60:
            penalties["emotional_plausibility"] += 1.0
        else:
            penalties["emotional_plausibility"] += 2.5

        # 感情インパクトの大きさに対する文体の変化
        if abs(event.emotional_impact) > 0.7:
            # 高インパクト時に断定文比率が高すぎる場合は減点
            assertive_markers = diary_text.count("だ。") + diary_text.count("である。")
            if assertive_markers > 3:
                penalties["persona_deviation"] += 1.0
                details["excessive_assertions"] = assertive_markers

            # 高インパクト日の文体特徴チェック (Prompt_Generator.md §emotional_impact)
            # 短文連打・比喩崩壊・口語混入・哲学中断が必要

            # 短文連打: 8文字以下の文が3回以上「連続」している箇所があるか
            # 「意味わからない」(7文字) 等も短文として認識する
            has_short_burst = False
            consecutive_short = 0
            for s in sentences:
                if 0 < len(s) <= 8:
                    consecutive_short += 1
                    if consecutive_short >= 3:
                        has_short_burst = True
                        break
                else:
                    consecutive_short = 0

            colloquial_markers = ("ムカつく", "意味わからん", "普通に", "マジで", "嫌")
            has_colloquial = any(m in diary_text for m in colloquial_markers)
            interruption_markers = ("いや、", "——いや", "とか関係ない", "そんな話じゃない")
            has_interruption = any(m in diary_text for m in interruption_markers)

            high_impact_features = sum([has_short_burst, has_colloquial, has_interruption])
            details["high_impact_features"] = high_impact_features
            details["has_short_burst"] = has_short_burst
            details["has_colloquial"] = has_colloquial
            details["has_interruption"] = has_interruption

            # 高インパクト日なのに文体が整然としすぎている場合は段階的減点
            if high_impact_features < 2:
                penalties["persona_deviation"] += 2.5
                details["emotional_collapse_failed"] = True
            elif high_impact_features < 3:
                penalties["persona_deviation"] += 1.0
                details["emotional_collapse_partial"] = True
            else:
                # 感情決壊文体が十分に達成されている場合はボーナス
                base_scores["persona_deviation"] += 0.5
                details["emotional_collapse_achieved"] = True

        def _clamp(field: str) -> float:
            return max(1.0, min(5.0, base_scores[field] - penalties[field]))

        return LayerScore(
            temporal_consistency=_clamp("temporal_consistency"),
            emotional_plausibility=_clamp("emotional_plausibility"),
            persona_deviation=_clamp("persona_deviation"),
            details=details,
        )


# ---------------------------------------------------------------------------
# Layer 3: LLMJudge (定性評価) -- 既存 Critic クラスをラップ
# ---------------------------------------------------------------------------


class LLMJudge:
    """Layer 3: LLM による定性評価。

    既存の Critic プロンプト (Prompt_Critic.md) を使用し、
    Layer 1/2 の結果をコンテキストとして渡す。
    """

    def __init__(
        self,
        client: LLMClient,
        config: CSDGConfig,
        prompts_dir: Path | None = None,
    ) -> None:
        """LLMJudge を初期化する。

        Args:
            client: LLM API クライアント。
            config: パイプライン設定。
            prompts_dir: プロンプトファイルのディレクトリパス。None の場合はデフォルト。
        """
        self._client = client
        self._config = config
        self._prompts_dir = prompts_dir or _DEFAULT_PROMPTS_DIR

    async def evaluate(
        self,
        diary_text: str,
        prev_state: CharacterState,
        curr_state: CharacterState,
        event: DailyEvent,
        expected_delta: dict[str, float],
        deviation: dict[str, float],
        layer1_result: LayerScore,
        layer2_result: LayerScore,
        prev_day_ending: str = "",
    ) -> tuple[LayerScore, float]:
        """LLM による定性評価を実行する。

        Args:
            diary_text: 評価対象の日記テキスト。
            prev_state: 前日の状態。
            curr_state: 今日の状態。
            event: 当日のイベント。
            expected_delta: 期待変動幅。
            deviation: 期待変動との乖離。
            layer1_result: RuleBasedValidator の結果。
            layer2_result: StatisticalChecker の結果。
            prev_day_ending: 前日の日記の末尾段落テキスト。フック回収検証用。

        Returns:
            (LayerScore, inverse_estimation_score) のタプル。
            inverse_estimation_score は 1.0-5.0 の逆推定一致スコア。
        """
        system_prompt = load_prompt(self._prompts_dir, "System_Persona.md")
        user_prompt = self._build_prompt(
            diary_text=diary_text,
            curr_state=curr_state,
            event=event,
            expected_delta=expected_delta,
            deviation=deviation,
            layer1_result=layer1_result,
            layer2_result=layer2_result,
            prev_day_ending=prev_day_ending,
        )

        critic_score = await self._client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=CriticScore,
            temperature=self._config.initial_temperature,
        )

        # 逆推定一致スコアの算出 (LLM の emotional_plausibility を基準にヒューリスティック算出)
        # deviation が大きいほど逆推定一致が低くなる
        inverse_score = self._compute_inverse_estimation(
            diary_text,
            curr_state,
            deviation,
        )

        return (
            LayerScore(
                temporal_consistency=float(critic_score.temporal_consistency),
                emotional_plausibility=float(critic_score.emotional_plausibility),
                persona_deviation=float(critic_score.persona_deviation),
                details={
                    "reject_reason": critic_score.reject_reason,
                    "revision_instruction": critic_score.revision_instruction,
                    "inverse_estimation_score": inverse_score,
                    "hook_strength": critic_score.hook_strength,
                },
            ),
            inverse_score,
        )

    def _compute_inverse_estimation(
        self,
        diary_text: str,
        curr_state: CharacterState,
        deviation: dict[str, float],
    ) -> float:
        """状態-文章の因果整合性を数値的に推定する。

        deviation の大きさに基づいて 1.0-5.0 のスコアを算出する。
        deviation が小さいほど状態と文章が一致していると判断する。
        """
        if not deviation:
            return 5.0
        max_dev = max(abs(v) for v in deviation.values())
        # max_dev: 0.0 -> 5.0, 0.5 -> 3.0, 1.0+ -> 1.0
        score = max(1.0, min(5.0, 5.0 - max_dev * 4.0))
        return round(score, 1)

    def _build_prompt(
        self,
        diary_text: str,
        curr_state: CharacterState,
        event: DailyEvent,
        expected_delta: dict[str, float],
        deviation: dict[str, float],
        layer1_result: LayerScore,
        layer2_result: LayerScore,
        prev_day_ending: str = "",
    ) -> str:
        """Layer 1/2 の結果を含む Critic プロンプトを構築する。"""
        template = load_prompt(self._prompts_dir, "Prompt_Critic.md")

        layer_context = (
            "以下は決定論的検証 (Layer 1) と統計的検証 (Layer 2) の結果です。\n"
            "これらの問題を踏まえて採点してください。\n\n"
            f"### Layer 1 (RuleBased)\n"
            f"- temporal: {layer1_result.temporal_consistency:.1f}\n"
            f"- emotional: {layer1_result.emotional_plausibility:.1f}\n"
            f"- persona: {layer1_result.persona_deviation:.1f}\n"
            f"- details: {layer1_result.details}\n\n"
            f"### Layer 2 (Statistical)\n"
            f"- temporal: {layer2_result.temporal_consistency:.1f}\n"
            f"- emotional: {layer2_result.emotional_plausibility:.1f}\n"
            f"- persona: {layer2_result.persona_deviation:.1f}\n"
            f"- details: {layer2_result.details}\n"
        )

        # HumanCondition のフォーマット
        hc = curr_state.human_condition
        hc_lines = [
            f"- 睡眠の質: {hc.sleep_quality:.2f}",
            f"- 身体的エネルギー: {hc.physical_energy:.2f}",
            f"- 気分ベースライン: {hc.mood_baseline:.2f}",
            f"- 認知負荷: {hc.cognitive_load:.2f}",
            f"- 感情的葛藤: {hc.emotional_conflict or 'なし'}",
        ]
        human_condition_text = "\n".join(hc_lines)

        return template.format(
            diary_text=diary_text,
            current_state=curr_state.model_dump_json(indent=2),
            event=event.model_dump_json(indent=2),
            human_condition=human_condition_text,
            expected_delta=expected_delta,
            deviation=deviation,
            layer_results=layer_context,
            prev_day_ending=prev_day_ending if prev_day_ending else "(初日のため参照なし)",
        )


# ---------------------------------------------------------------------------
# CriticPipeline: 3層統合
# ---------------------------------------------------------------------------


class CriticPipeline:
    """3層 Critic パイプライン。

    RuleBasedValidator -> StatisticalChecker -> LLMJudge の順に実行し、
    重み付き加重平均で最終 CriticScore を算出する。
    """

    def __init__(
        self,
        client: LLMClient,
        config: CSDGConfig,
        prompts_dir: Path | None = None,
    ) -> None:
        """CriticPipeline を初期化する。

        Args:
            client: LLM API クライアント。
            config: パイプライン設定。
            prompts_dir: プロンプトファイルのディレクトリパス。None の場合はデフォルト。
        """
        self._config = config
        self._weights = config.critic_weights
        self._veto_caps = config.veto_caps
        self._rule_based = RuleBasedValidator()
        self._statistical = StatisticalChecker()
        self._llm_judge = LLMJudge(client, config, prompts_dir)

    async def evaluate(
        self,
        prev_state: CharacterState,
        curr_state: CharacterState,
        diary_text: str,
        event: DailyEvent,
        prev_diary: str | None = None,
        prev_day_ending: str = "",
    ) -> CriticResult:
        """3層評価を実行し、CriticResult を返す。

        Args:
            prev_state: 前日の状態。
            curr_state: 今日の状態。
            diary_text: 評価対象の日記テキスト。
            event: 当日のイベント。
            prev_diary: 前日の日記テキスト (重複チェック用)。
            prev_day_ending: 前日の日記の末尾段落テキスト (フック回収検証用)。

        Returns:
            CriticResult (各層スコア + 統合 CriticScore)。
        """
        expected_delta = compute_expected_delta(event, self._config.emotion_sensitivity)
        deviation = compute_deviation(prev_state, curr_state, expected_delta)

        # Layer 1: RuleBased
        layer1 = self._rule_based.evaluate(
            diary_text,
            prev_state,
            curr_state,
            event,
            expected_delta,
            prev_diary,
        )

        # Layer 2: Statistical
        layer2 = self._statistical.evaluate(
            diary_text,
            prev_state,
            curr_state,
            event,
            expected_delta,
            deviation,
        )

        # Layer 3: LLMJudge (逆推定一致スコアも返す)
        layer3, inverse_score = await self._llm_judge.evaluate(
            diary_text,
            prev_state,
            curr_state,
            event,
            expected_delta,
            deviation,
            layer1,
            layer2,
            prev_day_ending=prev_day_ending,
        )

        # Veto 判定
        veto_flags = self._rule_based.has_critical_failure(layer1)

        # 重み付き加重平均で最終スコアを算出 (veto 権 + 逆推定一致チェック付き)
        final_score = self._compute_final_score(
            layer1,
            layer2,
            layer3,
            veto_flags,
            inverse_score,
        )

        logger.info(
            "[Day %d] CriticPipeline: L1=%.1f/%.1f/%.1f L2=%.1f/%.1f/%.1f L3=%.1f/%.1f/%.1f -> %d/%d/%d (inv=%.1f)",
            event.day,
            layer1.temporal_consistency,
            layer1.emotional_plausibility,
            layer1.persona_deviation,
            layer2.temporal_consistency,
            layer2.emotional_plausibility,
            layer2.persona_deviation,
            layer3.temporal_consistency,
            layer3.emotional_plausibility,
            layer3.persona_deviation,
            final_score.temporal_consistency,
            final_score.emotional_plausibility,
            final_score.persona_deviation,
            inverse_score,
        )

        return CriticResult(
            rule_based=layer1,
            statistical=layer2,
            llm_judge=layer3,
            final_score=final_score,
            weights={
                "rule_based": self._weights.rule_based,
                "statistical": self._weights.statistical,
                "llm_judge": self._weights.llm_judge,
            },
            inverse_estimation_score=inverse_score,
            veto_applied=veto_flags,
        )

    def _compute_final_score(
        self,
        layer1: LayerScore,
        layer2: LayerScore,
        layer3: LayerScore,
        veto_flags: dict[str, bool] | None = None,
        inverse_estimation_score: float | None = None,
    ) -> CriticScore:
        """3層のスコアを重み付き加重平均で統合する (veto 権付き)。

        veto 発動時は該当軸のスコアに上限キャップを適用する。
        逆推定一致スコアが 2 以下の場合、emotional 軸に veto を適用する。
        """
        w = self._weights
        caps = self._veto_caps
        effective_veto = dict(veto_flags) if veto_flags else {f: False for f in _SCORE_FIELDS}

        # 逆推定一致スコアが低い場合、emotional 軸に veto
        if inverse_estimation_score is not None and inverse_estimation_score <= 2.0:
            effective_veto["emotional_plausibility"] = True

        scores: dict[str, int] = {}
        veto_cap_map: dict[str, float] = {
            "temporal_consistency": caps.temporal,
            "emotional_plausibility": caps.emotional,
            "persona_deviation": caps.persona,
        }

        w_l12_sum = w.rule_based + w.statistical

        for field in _SCORE_FIELDS:
            weighted = (
                getattr(layer1, field) * w.rule_based
                + getattr(layer2, field) * w.statistical
                + getattr(layer3, field) * w.llm_judge
            )

            # L1/L2 コンセンサス補正: L1/L2 と L3 の乖離を増幅
            l1_val = getattr(layer1, field)
            l2_val = getattr(layer2, field)
            l3_val = getattr(layer3, field)
            l12_norm = (l1_val * w.rule_based + l2_val * w.statistical) / w_l12_sum
            correction = (l12_norm - l3_val) * _CONSENSUS_AMPLIFICATION
            amplified = weighted + correction

            # 安全制限: 補正前との差を±_MAX_SCORE_ADJUSTMENT に制限
            non_amplified = max(1, min(5, round(weighted)))
            final = max(1, min(5, round(amplified)))
            score = max(
                non_amplified - _MAX_SCORE_ADJUSTMENT,
                min(non_amplified + _MAX_SCORE_ADJUSTMENT, final),
            )

            # Veto は安全制限の後に強制適用 (安全制限をバイパス)
            if effective_veto.get(field):
                cap = veto_cap_map[field]
                score = min(score, max(1, min(5, round(cap))))
                logger.info("[Veto] %s capped to %d (was %d)", field, score, non_amplified)

            scores[field] = score

        # reject_reason / revision_instruction は LLMJudge から取得
        reject_reason = layer3.details.get("reject_reason")
        revision_instruction = layer3.details.get("revision_instruction")

        is_reject = any(v < 3 for v in scores.values())
        if is_reject and not reject_reason:
            reject_reason = "Layer 1/2 の検証で問題が検出されました"
        if is_reject and not revision_instruction:
            revision_instruction = "Layer 1/2 で検出された問題を修正してください"

        # L3 (LLMJudge) が返した hook_strength を最終スコアに転送
        l3_hook = layer3.details.get("hook_strength", 0.0)
        hook_val = max(0.0, min(1.0, float(l3_hook))) if isinstance(l3_hook, (int, float)) else 0.0

        return CriticScore(
            temporal_consistency=scores["temporal_consistency"],
            emotional_plausibility=scores["emotional_plausibility"],
            persona_deviation=scores["persona_deviation"],
            hook_strength=hook_val,
            reject_reason=str(reject_reason) if reject_reason else None,
            revision_instruction=str(revision_instruction) if revision_instruction else None,
        )


# ---------------------------------------------------------------------------
# Critic クラス (後方互換性を維持)
# ---------------------------------------------------------------------------


class Critic:
    """Phase 3 (評価) を担当する。

    CriticPipeline を内部で使用し、既存の evaluate() インターフェースを維持する。
    """

    def __init__(
        self,
        client: LLMClient,
        config: CSDGConfig,
        prompts_dir: Path | None = None,
    ) -> None:
        """Critic を初期化する。

        Args:
            client: LLM API クライアント。
            config: パイプライン設定。
            prompts_dir: プロンプトファイルのディレクトリパス。None の場合はデフォルト。
        """
        self._pipeline = CriticPipeline(client, config, prompts_dir)

    async def evaluate(
        self,
        prev_state: CharacterState,
        curr_state: CharacterState,
        diary_text: str,
        event: DailyEvent,
    ) -> CriticScore:
        """日記テキストと状態を評価し、CriticScore を返す。

        内部で CriticPipeline を使用し、3層評価を実行する。
        後方互換性のため CriticScore のみを返す。

        Args:
            prev_state: 前日のキャラクター内部状態 (h_{t-1})。
            curr_state: 今日のキャラクター内部状態 (h_t)。
            diary_text: Phase 2 で生成された日記テキスト。
            event: 当日のイベント定義。

        Returns:
            CriticScore インスタンス。
        """
        result = await self.evaluate_full(prev_state, curr_state, diary_text, event)
        return result.final_score

    async def evaluate_full(
        self,
        prev_state: CharacterState,
        curr_state: CharacterState,
        diary_text: str,
        event: DailyEvent,
        prev_diary: str | None = None,
        prev_day_ending: str = "",
    ) -> CriticResult:
        """日記テキストと状態を評価し、CriticResult (3層詳細) を返す。

        Args:
            prev_state: 前日のキャラクター内部状態 (h_{t-1})。
            curr_state: 今日のキャラクター内部状態 (h_t)。
            diary_text: Phase 2 で生成された日記テキスト。
            event: 当日のイベント定義。
            prev_diary: 前日の日記テキスト (重複チェック用)。
            prev_day_ending: 前日の日記の末尾段落テキスト (フック回収検証用)。

        Returns:
            CriticResult インスタンス (3層スコア + 統合スコア)。
        """
        return await self._pipeline.evaluate(
            prev_state,
            curr_state,
            diary_text,
            event,
            prev_diary=prev_diary,
            prev_day_ending=prev_day_ending,
        )
