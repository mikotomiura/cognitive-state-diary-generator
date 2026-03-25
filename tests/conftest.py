"""tests/conftest.py -- 共通フィクスチャ定義。

fixture-patterns.md のパターンに従い、データ・設定・モックのフィクスチャを提供する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from csdg.config import CSDGConfig
from csdg.engine.llm_client import LLMClient
from csdg.schemas import CharacterState, CriticScore, DailyEvent

# --- データフィクスチャ ---


@pytest.fixture()
def initial_state() -> CharacterState:
    """シナリオの初期状態 h_0。"""
    return CharacterState(
        fatigue=0.1,
        motivation=0.2,
        stress=-0.1,
        current_focus="来週の社内コードレビュー会の準備",
        unresolved_issue=None,
        growth_theme="「考えること」と「生きること」の折り合い",
        memory_buffer=[],
        relationships={"深森那由他": 0.6, "ミナ": 0.4},
    )


@pytest.fixture()
def sample_event() -> DailyEvent:
    """Day 1 のイベント (neutral, impact=+0.2)。"""
    return DailyEvent(
        day=1,
        event_type="neutral",
        domain="仕事",
        description="社内ツールの自動化スクリプトが完成し、30分かかっていた作業が2分に短縮された",
        emotional_impact=0.2,
    )


@pytest.fixture()
def high_impact_event() -> DailyEvent:
    """Day 4 のイベント (negative, impact=-0.9)。ストレステスト用。"""
    return DailyEvent(
        day=4,
        event_type="negative",
        domain="仕事",
        description="全社会議で経営陣が全業務のAI自動化ロードマップを発表した",
        emotional_impact=-0.9,
    )


@pytest.fixture()
def pass_score() -> CriticScore:
    """全スコア3以上の合格スコア。"""
    return CriticScore(
        temporal_consistency=4,
        emotional_plausibility=4,
        persona_deviation=5,
    )


@pytest.fixture()
def reject_score() -> CriticScore:
    """persona_deviation が2の不合格スコア。"""
    return CriticScore(
        temporal_consistency=4,
        emotional_plausibility=3,
        persona_deviation=2,
        reject_reason="絵文字が使用されている",
        revision_instruction="絵文字を削除し、言葉のみで感情を表現してください",
    )


@pytest.fixture()
def sample_diary() -> str:
    """テスト用の日記テキスト。"""
    return (
        "今日、自動化スクリプトが完成した。30分の作業が2分になった。\n\n"
        "チームからは感謝された。でも、わたしの中では妙な手持ち無沙汰が残っている。\n"
        "効率化が成功したのに、この空虚さは何なんだろう......。\n\n"
        "帰り道、ふと利休のことを考えた。"
        "あの人は、お茶を点てるのに最も効率的な方法を選ばなかった。\n"
        "むしろ非効率な所作にこそ意味があると信じていた......のかもしれない。"
    )


# --- 設定フィクスチャ ---


@pytest.fixture()
def test_config() -> CSDGConfig:
    """テスト用の設定 (API キーはダミー)。"""
    return CSDGConfig(
        llm_api_key="test-api-key-dummy",
        llm_model="claude-sonnet-4-20250514",
        max_retries=3,
        initial_temperature=0.7,
        output_dir="test_output",
    )


# --- モックフィクスチャ ---


@pytest.fixture()
def mock_llm_client() -> LLMClient:
    """LLM API をモックしたクライアント。"""
    return AsyncMock(spec=LLMClient)
