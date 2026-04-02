"""
シナリオ定義モジュール。

7日分の DailyEvent (SCENARIO) と初期状態 (INITIAL_STATE) を定義する。
functional-design.md §8 のシナリオ仕様および glossary.md の用語定義に準拠する。
"""

from __future__ import annotations

from csdg.schemas import CharacterState, DailyEvent, HumanCondition

# ---------------------------------------------------------------------------
# 7日分の DailyEvent リスト
# ---------------------------------------------------------------------------

SCENARIO: list[DailyEvent] = [
    DailyEvent(
        day=1,
        event_type="neutral",
        domain="仕事",
        description=(
            "自動化スクリプトが完璧に動いた。手作業で30分かかっていた日次集計が"
            "3秒で終わる。チームは喜んでいるが、とこみは画面に並ぶグリーンのチェックマークを"
            "見ながら、妙な空虚感を覚える。"
            "「わたしの30分は、3秒の価値しかなかったのか」"
        ),
        emotional_impact=-0.15,
    ),
    DailyEvent(
        day=2,
        event_type="positive",
        domain="趣味",
        description=(
            "仕事帰り、神保町の古書店で偶然見つけた岡倉天心の『茶の本』初版。"
            "店主が「これ、読む人久しぶりだねぇ」と笑った。"
            "帰りの電車で数ページ読んで、大学院時代の茶道研究のことを鮮烈に思い出す。"
        ),
        emotional_impact=0.5,
    ),
    DailyEvent(
        day=3,
        event_type="negative",
        domain="仕事",
        description=(
            "コードレビューで那由他さんに「動くけど読めない」と指摘される。"
            "10行の関数を1行のラムダ式に圧縮したコード。"
            "技術的には正しいのに、なぜ否定された気分になるのか自分でもわからない。"
        ),
        emotional_impact=-0.4,
    ),
    DailyEvent(
        day=4,
        event_type="negative",
        domain="内省",
        description=(
            "深夜2時、眠れなくて自分の過去のブログを遡っていたら、"
            "1年前の自分が『効率化こそ正義。無駄を省くことが知性の証明』と"
            "断言していた記事を見つけた。あの頃のわたしは確信に満ちていた。"
            "今のわたしは何に満ちているのか全くわからない。"
            "気づいたら画面に向かって「うるさい」と声に出していた。"
        ),
        emotional_impact=-0.8,
    ),
    DailyEvent(
        day=5,
        event_type="positive",
        domain="人間関係",
        description=(
            "古書店でミナと偶然会う。岡倉天心の話をしたら、"
            "「とこみちゃんの話、ブログに書いたら面白いのに」と言われる。"
            "「誰も読まないよ」と返したが、帰り道ずっとその言葉が頭に残っている。"
            "「昨夜のことは誰にも言えない。けれど、ミナの前では不思議と言葉が出てきた。」"
        ),
        emotional_impact=0.3,
    ),
    DailyEvent(
        day=6,
        event_type="positive",
        domain="仕事",
        description=(
            "あの1行ラムダ式を、那由他さんのアドバイスに従って5行の関数に書き直した。"
            "実行速度は0.2秒遅くなった。でも那由他さんが「これなら半年後の自分が読める」"
            "と言ったとき、『茶の本』の一節がふと浮かんだ。"
            "「不完全なものを前にして、それを心の中で完成させる——」"
        ),
        emotional_impact=0.35,
    ),
    DailyEvent(
        day=7,
        event_type="positive",
        domain="思想",
        description=(
            "日曜日の午後、近所のカフェでぼんやりしながら、"
            "この1週間のことを振り返っている。"
            "効率と非効率、圧縮と余白、正しさと読みやすさ。"
            "1年前の自分を論破できるわけでもないし、今の自分が正しいとも思わない。"
            "でも来週もこのブログは書き続ける気がする。"
        ),
        emotional_impact=0.25,
    ),
]

# ---------------------------------------------------------------------------
# 初期状態 (h_0)
# ---------------------------------------------------------------------------

INITIAL_STATE: CharacterState = CharacterState(
    fatigue=0.1,
    motivation=0.2,
    stress=-0.1,
    current_focus="自動化スクリプトの本番投入が完了した直後の微妙な手持ち無沙汰",
    unresolved_issue=None,
    growth_theme="「考えること」と「生きること」の折り合い",
    memory_buffer=[],
    relationships={"深森那由他": 0.6, "ミナ": 0.4},
    human_condition=HumanCondition(
        sleep_quality=0.55,
        physical_energy=0.6,
        mood_baseline=-0.15,
        cognitive_load=0.3,
        emotional_conflict=None,
    ),
)


# ---------------------------------------------------------------------------
# バリデーション関数
# ---------------------------------------------------------------------------


def validate_scenario(events: list[DailyEvent]) -> None:
    """シナリオのバリデーションを行う。

    Args:
        events: バリデーション対象の DailyEvent リスト。

    Raises:
        ValueError: day が 1 から始まる連番でない場合、
            または emotional_impact が範囲外の場合。
    """
    if not events:
        raise ValueError("イベントリストが空です")

    for i, event in enumerate(events):
        expected_day = i + 1
        if event.day != expected_day:
            raise ValueError(f"day が連番ではありません: 位置 {i} で day={event.day} (期待値: {expected_day})")
        # emotional_impact の範囲チェックは DailyEvent.field_validator が実施済み
