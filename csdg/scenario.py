"""
シナリオ定義モジュール。

7日分の DailyEvent (SCENARIO) と初期状態 (INITIAL_STATE) を定義する。
functional-design.md §8 のシナリオ仕様および glossary.md の用語定義に準拠する。
"""

from __future__ import annotations

from csdg.schemas import CharacterState, DailyEvent

# ---------------------------------------------------------------------------
# 7日分の DailyEvent リスト
# ---------------------------------------------------------------------------

SCENARIO: list[DailyEvent] = [
    DailyEvent(
        day=1,
        event_type="neutral",
        domain="仕事",
        emotional_impact=0.2,
        description="自動化スクリプトが完成し業務効率は上がったが、手持ち無沙汰な虚しさが残る。コードレビュー会の準備中、効率だけを追う空気に微かな違和感を覚える",
    ),
    DailyEvent(
        day=2,
        event_type="positive",
        domain="趣味",
        emotional_impact=0.6,
        description="古書店で西田幾多郎の初版本を偶然発見し、非効率な時間の深い喜びを味わう",
    ),
    DailyEvent(
        day=3,
        event_type="negative",
        domain="仕事",
        emotional_impact=-0.5,
        description="社内コードレビュー会でとこみの設計提案がPMに一蹴され、問いを立てること自体を否定される",
    ),
    DailyEvent(
        day=4,
        event_type="negative",
        domain="仕事・思想",
        emotional_impact=-0.9,
        description="全社会議でAI自動化ロードマップが発表され、人間の思考が不要とされる方針に感情が爆発する",
    ),
    DailyEvent(
        day=5,
        event_type="neutral",
        domain="人間関係・内省",
        emotional_impact=0.15,
        description="まだ昨日の衝撃が抜けきらない中、古書店仲間のミナと短く話す。「あなたは表現者だ」という言葉が耳に残るが、今はまだ救いにはならない",
    ),
    DailyEvent(
        day=6,
        event_type="neutral",
        domain="人間関係・内省",
        emotional_impact=0.5,
        description="大学院時代の現象学ノートを発見し、那由他に連絡を取る。短いやり取りの中で過去の研究と現在の違和感が接続され始める",
    ),
    DailyEvent(
        day=7,
        event_type="positive",
        domain="仕事",
        emotional_impact=0.5,
        description="暗黙知の可視化という小さな提案を職場に持ち込み、問いを仕事に接続する一歩を踏み出す",
    ),
]

# ---------------------------------------------------------------------------
# 初期状態 (h_0)
# ---------------------------------------------------------------------------

INITIAL_STATE: CharacterState = CharacterState(
    fatigue=0.1,
    motivation=0.2,
    stress=-0.1,
    current_focus="来週の社内コードレビュー会の準備",
    unresolved_issue=None,
    growth_theme="「考えること」と「生きること」の折り合い",
    memory_buffer=[],
    relationships={"深森那由他": 0.6, "ミナ": 0.4},
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
