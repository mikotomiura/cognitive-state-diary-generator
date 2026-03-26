"""CSDG パイプラインの CLI エントリポイント。

functional-design.md §4 (CLI インターフェース仕様) および
architecture.md §7 (出力・可視化設計) に準拠する。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from csdg.config import CSDGConfig
from csdg.engine.actor import Actor
from csdg.engine.critic import Critic
from csdg.engine.llm_client import AnthropicClient
from csdg.engine.pipeline import PipelineRunner
from csdg.scenario import INITIAL_STATE, SCENARIO, validate_scenario

if TYPE_CHECKING:
    from csdg.schemas import GenerationRecord

logger = logging.getLogger(__name__)

_REQUIRED_PROMPTS = [
    "System_Persona.md",
    "Prompt_StateUpdate.md",
    "Prompt_Generator.md",
    "Prompt_Critic.md",
]

# 終了コード (functional-design.md §4.3)
_EXIT_OK = 0
_EXIT_PARTIAL = 1
_EXIT_ABORT = 2
_EXIT_CONFIG_ERROR = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 引数を解析する。

    Args:
        argv: 引数リスト。None の場合は sys.argv を使用。

    Returns:
        解析済みの Namespace。
    """
    parser = argparse.ArgumentParser(
        prog="csdg",
        description="Cognitive-State Diary Generator -- AI キャラクター日記生成パイプライン",
    )
    parser.add_argument("--day", type=int, default=None, help="特定の Day のみ実行する")
    parser.add_argument("--output-dir", type=str, default=None, help="出力ディレクトリ (デフォルト: output)")
    parser.add_argument("--verbose", action="store_true", help="詳細ログを表示する")
    parser.add_argument("--skip-visualization", action="store_true", help="グラフ生成をスキップする")
    parser.add_argument("--dry-run", action="store_true", help="API 呼び出しなしの構成確認")
    return parser.parse_args(argv)


def save_diary(record: GenerationRecord, output_dir: str) -> Path:
    """日記を YAML フロントマター付き Markdown として保存する。

    Args:
        record: 1Day 分の生成記録。
        output_dir: 出力ディレクトリパス。

    Returns:
        保存したファイルのパス。
    """
    path = Path(output_dir) / f"day_{record.day:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    last_score = record.critic_scores[-1] if record.critic_scores else None

    frontmatter_lines = [
        "---",
        f"day: {record.day}",
        f'generated_at: "{datetime.now(tz=UTC).isoformat()}"',
        f'event_type: "{record.event.event_type}"',
        f'domain: "{record.event.domain}"',
        f"emotional_impact: {record.event.emotional_impact}",
        "state:",
        f"  fatigue: {record.final_state.fatigue}",
        f"  motivation: {record.final_state.motivation}",
        f"  stress: {record.final_state.stress}",
        f'  current_focus: "{record.final_state.current_focus}"',
        f'  growth_theme: "{record.final_state.growth_theme}"',
    ]

    if last_score is not None:
        frontmatter_lines.extend(
            [
                "critic_score:",
                f"  temporal_consistency: {last_score.temporal_consistency}",
                f"  emotional_plausibility: {last_score.emotional_plausibility}",
                f"  persona_deviation: {last_score.persona_deviation}",
            ]
        )

    frontmatter_lines.extend(
        [
            f"retry_count: {record.retry_count}",
            f"fallback_used: {'true' if record.fallback_used else 'false'}",
            "---",
        ]
    )

    content = "\n".join(frontmatter_lines) + "\n\n" + record.diary_text + "\n"
    path.write_text(content, encoding="utf-8")

    logger.info("[Day %d] Saved: %s", record.day, path)
    return path


async def run_pipeline(args: argparse.Namespace) -> int:
    """パイプラインを実行する。

    Args:
        args: CLI 引数。

    Returns:
        終了コード。
    """
    # 1. 設定読み込み
    try:
        config = CSDGConfig()
    except Exception:
        logger.exception("[CSDG] 設定の読み込みに失敗しました")
        return _EXIT_CONFIG_ERROR

    output_dir = args.output_dir or config.output_dir

    # 2. プロンプトファイルの存在確認
    prompts_dir = Path("prompts")
    for filename in _REQUIRED_PROMPTS:
        if not (prompts_dir / filename).exists():
            logger.error("[CSDG] プロンプトファイルが見つかりません: %s", prompts_dir / filename)
            return _EXIT_CONFIG_ERROR

    # 3. シナリオのバリデーション
    try:
        validate_scenario(SCENARIO)
    except ValueError:
        logger.exception("[CSDG] シナリオのバリデーションに失敗しました")
        return _EXIT_CONFIG_ERROR

    # イベントのフィルタリング (--day オプション)
    events = SCENARIO
    if args.day is not None:
        events = [e for e in SCENARIO if e.day == args.day]
        if not events:
            logger.error("[CSDG] Day %d のイベントが見つかりません", args.day)
            return _EXIT_CONFIG_ERROR

    logger.info("[CSDG] Starting pipeline (Day %d-%d)", events[0].day, events[-1].day)

    if args.verbose:
        logger.info(
            "[CSDG] Config: model=%s, max_retries=%d, initial_temp=%.1f",
            config.llm_model,
            config.max_retries,
            config.initial_temperature,
        )
        logger.info("[CSDG] Loaded %d events from scenario.py", len(events))

    # Dry-run: 構成確認のみ
    if args.dry_run:
        logger.info("[CSDG] Dry-run mode -- 構成確認完了、API 呼び出しはスキップ")
        return _EXIT_OK

    # 4-6. パイプライン構築・実行
    client = AnthropicClient(
        api_key=config.llm_api_key,
        model=config.llm_model,
        base_url=config.llm_base_url,
    )
    actor = Actor(client, config)
    critic = Critic(client, config)
    runner = PipelineRunner(config, actor, critic, llm_client=client)

    pipeline_log = await runner.run(events, INITIAL_STATE)

    # 7. 日記ファイル保存
    for record in pipeline_log.records:
        save_diary(record, output_dir)

    # 8. generation_log.json 保存
    log_path = Path(output_dir) / "generation_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(
            json.loads(pipeline_log.model_dump_json()),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("[CSDG] Saved: %s", log_path)

    # 9. CriticLog 永続化
    critic_log_path = Path(output_dir) / "critic_log.jsonl"
    runner.critic_log.save(critic_log_path)
    logger.info("[CSDG] Saved: %s", critic_log_path)

    # 10. 可視化
    if not args.skip_visualization:
        from csdg.visualization import generate_state_trajectory

        viz_path = str(Path(output_dir) / "state_trajectory.png")
        generate_state_trajectory(pipeline_log, output_path=viz_path)
        logger.info("[CSDG] Saved: %s", viz_path)

    # 終了コード判定
    total_events = len(events)
    total_records = len(pipeline_log.records)
    if total_records == total_events:
        return _EXIT_OK
    if total_records > 0:
        return _EXIT_PARTIAL
    return _EXIT_ABORT


def main() -> None:
    """エントリポイント。"""
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    # サードパーティのDEBUGログを抑制
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    exit_code = asyncio.run(run_pipeline(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
