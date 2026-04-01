"""
プロンプトファイル読み込みユーティリティ。

prompts/ ディレクトリからプロンプトファイルを読み込む共通関数を提供する。
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — runtime で使用


def load_prompt(prompts_dir: Path, filename: str) -> str:
    """prompts/ ディレクトリからプロンプトファイルを読み込む。

    Args:
        prompts_dir: プロンプトファイルのディレクトリパス。
        filename: プロンプトファイル名 (例: "System_Persona.md")。

    Returns:
        プロンプトファイルの内容。

    Raises:
        FileNotFoundError: 指定されたファイルが存在しない場合。
    """
    path = prompts_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"プロンプトファイルが見つかりません: {path}")
    return path.read_text(encoding="utf-8")
