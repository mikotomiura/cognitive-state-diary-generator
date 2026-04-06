# 開発ガイドライン (Development Guidelines)

> **目的:** CSDG プロジェクトの開発プロセス全体を規定する。コーディング規約、Git運用、テスト方針、レビュー基準、セキュリティ方針を統一し、品質と生産性を両立させる。
> 「何を作るか」は `functional-design.md` に、「どこに置くか」は `repository-structure.md` に委譲する。
> 本ドキュメントは「どのように開発するか」を記述する。

---

## 1. 開発の原則

本プロジェクトの全開発作業は、以下の5原則に従う。迷ったときはこの原則に立ち返ること。

### 原則 1: 設計書ファースト

コードを書く前に、関連するドキュメントを読み、設計意図を理解する。
新機能の追加や設計変更を伴う場合は、先にドキュメントを更新し、その後にコードを実装する。

**確認すべきドキュメント:**
- `glossary.md` — 使用する用語が正しいか
- `functional-design.md` — 機能要件に合致しているか
- `architecture.md` — 技術設計に沿っているか
- `repository-structure.md` — ファイル配置は正しいか

### 原則 2: 型安全性の最優先

Pydanticモデルによる厳密な型定義を遵守する。`Any` 型の使用は原則禁止。
mypy strict modeでエラーが出ない状態を常に維持する。

### 原則 3: テストなしのコミット禁止

新機能・バグ修正には必ずテストを伴う。テストが書けない変更は設計に問題がある兆候と考える。

### 原則 4: プロンプトはコードに埋め込まない

LLMに渡すプロンプトは `prompts/` ディレクトリの外部Markdownファイルで管理する。
Pythonコード内に文字列リテラルとしてプロンプトを記述しない。

### 原則 5: Self-Healingを前提とする

LLMの出力は必ずパースエラーを起こしうるものとして扱う。正常系だけでなく、異常系のハンドリングを最初から設計に組み込む。

---

## 2. コーディング規約

### 2.1 全般

| 項目 | 規約 |
|---|---|
| Python バージョン | 3.11 以上 |
| 最大行長 | 120文字（ruff のデフォルト設定に従う） |
| インデント | スペース4つ |
| 文字エンコーディング | UTF-8 |
| 改行コード | LF |
| 末尾改行 | ファイル末尾に1つの空行を入れる |
| import順序 | ruff の isort 互換ルールに従う（標準ライブラリ → サードパーティ → ローカル） |

### 2.2 型アノテーション

すべての関数・メソッドに型アノテーションを付ける。mypy strict mode で検証する。

```python
# ✅ 良い例
def compute_expected_delta(event: DailyEvent, sensitivity: dict[str, float]) -> dict[str, float]:
    return {
        param: event.emotional_impact * coeff
        for param, coeff in sensitivity.items()
    }

# ❌ 悪い例（型アノテーションなし）
def compute_expected_delta(event, sensitivity):
    return {
        param: event.emotional_impact * coeff
        for param, coeff in sensitivity.items()
    }
```

**型アノテーションのルール:**
- 戻り値が `None` のみの場合は `-> None` を明記する
- `Optional[X]` よりも `X | None` を推奨する（Python 3.10+ 構文）
- コレクション型はジェネリクスを使用する（`list[str]`, `dict[str, float]`）
- `Any` 型は原則禁止。やむを得ず使用する場合はコメントで理由を記述する
- `TypeAlias` を活用し、複雑な型には名前をつける

```python
from typing import TypeAlias

# 複雑な型にはエイリアスを定義する
EmotionMap: TypeAlias = dict[str, float]
MemoryBuffer: TypeAlias = list[str]
```

### 2.3 docstring

すべてのモジュール・クラス・公開関数にdocstringを記述する。
フォーマットはGoogle styleに従う。

```python
def update_state(
    prev_state: CharacterState,
    event: DailyEvent,
    persona_prompt: str,
    update_prompt: str,
) -> CharacterState:
    """イベントに基づきキャラクターの内部状態を更新する。

    Phase 1（状態遷移）の処理を担当する。前日の状態 h_{t-1} と
    当日のイベント x_t を入力とし、新しい状態 h_t を返す。

    Args:
        prev_state: 前日のキャラクター内部状態 (h_{t-1})。
        event: 当日のイベント定義 (x_t)。
        persona_prompt: System_Persona.md の内容。
        update_prompt: Prompt_StateUpdate.md の展開済み内容。

    Returns:
        更新されたキャラクター内部状態 (h_t)。
        連続変数は -1.0〜1.0 にクランプ済み。

    Raises:
        pydantic.ValidationError: LLM出力がスキーマに適合しない場合。
            呼び出し元 (pipeline.py) でリトライ制御される。
    """
```

**docstring のルール:**
- 1行目は命令形の要約（「〜する。」で終わる）
- `Args`, `Returns`, `Raises` セクションは該当がある場合のみ記述する
- 用語は `glossary.md` に定義されたものを使用する
- プライベート関数（`_` プレフィックス）にもdocstringを書く（ただし簡潔でよい）

### 2.4 エラーハンドリング

```python
# ✅ 良い例: 具体的な例外をキャッチし、意味のあるメッセージを付ける
try:
    state = CharacterState.model_validate_json(raw_json)
except ValidationError as e:
    logger.warning(f"Phase 1 バリデーションエラー (Day {day}): {e.error_count()} errors")
    raise

# ❌ 悪い例: 裸の except
try:
    state = CharacterState.model_validate_json(raw_json)
except:
    pass
```

**エラーハンドリングのルール:**
- 裸の `except:` は禁止。必ず具体的な例外クラスをキャッチする
- `except Exception` は最外周（`main.py` のトップレベル、`pipeline.py` のDay単位ループ）でのみ許可する
- キャッチした例外は必ずログに記録する
- 例外を握りつぶす（`except ... : pass`）ことは禁止。フォールバック処理を明示的に記述する
- カスタム例外は `csdg/exceptions.py` に定義する（必要に応じて作成）

### 2.5 ロギング

```python
import logging

logger = logging.getLogger(__name__)
```

**ロギングのルール:**
- `print()` でのデバッグ出力は禁止。必ず `logging` モジュールを使用する
- ログレベルの使い分け:

| レベル | 用途 | 例 |
|---|---|---|
| `DEBUG` | 開発時の詳細情報 | プロンプトのトークン数、LLMレスポンスの先頭100文字 |
| `INFO` | 正常な処理の進行状況 | `[Day 1] Phase 1: State Update ... OK (1.2s)` |
| `WARNING` | 回復可能な問題 | バリデーションエラーによるリトライ、フォールバック発生 |
| `ERROR` | 回復不能な問題 | API接続失敗（リトライ上限超過）、Dayスキップ |
| `CRITICAL` | システム停止レベル | パイプライン中断（連続3Day失敗） |

### 2.6 定数と設定値

```python
# ✅ 良い例: 設定は config.py で一元管理
from csdg.config import CSDGConfig
config = CSDGConfig()
temperature = config.initial_temperature

# ❌ 悪い例: マジックナンバー
temperature = 0.7  # これは何の値？
```

**ルール:**
- ハードコードされた数値（マジックナンバー）は禁止
- 設定値は `config.py` の `CSDGConfig` クラスで管理する
- プロジェクト全体で不変の定数（例: 連続変数の範囲 `-1.0` 〜 `1.0`）は `schemas.py` 内の `field_validator` またはクラス変数で定義する

### 2.7 非同期処理

LLM API呼び出しは `async/await` で実装する。

```python
# ✅ 良い例
async def generate_structured(self, ...) -> BaseModel:
    response = await self.client.chat.completions.create(...)
    return response_model.model_validate_json(response.choices[0].message.content)

# パイプラインのエントリポイント
async def run(config: CSDGConfig, ...) -> PipelineLog:
    ...

# main.py
import asyncio

def main() -> None:
    asyncio.run(run(config, ...))
```

**ルール:**
- LLM API呼び出しを含む関数は `async` で定義する
- 同一Day内のPhase 1 → Phase 2 → Phase 3 は直列実行（依存関係があるため並列化不可）
- 将来的にDay間の並列実行が必要になった場合に備え、`async` 設計を採用しておく

---

## 3. Pydantic モデル設計規約

### 3.1 モデル定義の原則

```python
from pydantic import BaseModel, Field, field_validator

class CharacterState(BaseModel):
    """キャラクター内部状態 (h_t)。

    全連続変数は -1.0〜1.0 の範囲にクランプされる。
    """

    # 連続変数 — Field で説明と範囲を明示
    fatigue: float = Field(description="疲労度 (0.0: 元気 〜 1.0: 限界)")
    motivation: float = Field(description="モチベーション (-1.0: 虚無 〜 1.0: やる気満々)")
    stress: float = Field(description="ストレス値 (-1.0: リラックス 〜 1.0: 爆発寸前)")

    # 離散変数
    current_focus: str = Field(description="現在最も関心を持っている事柄")
    unresolved_issue: str | None = Field(default=None, description="未解決の悩みや課題")
    growth_theme: str = Field(description="1週間を通じた成長テーマ")

    # 累積記憶
    memory_buffer: list[str] = Field(default_factory=list, description="過去3日分のdaily_summary")
    relationships: dict[str, float] = Field(default_factory=dict, description="人物への好感度")

    @field_validator("fatigue", "motivation", "stress")
    @classmethod
    def clamp_continuous_vars(cls, v: float) -> float:
        """連続変数を -1.0〜1.0 の範囲にクランプする。"""
        return max(-1.0, min(1.0, v))

    @field_validator("memory_buffer")
    @classmethod
    def limit_memory_buffer(cls, v: list[str]) -> list[str]:
        """memory_buffer を最大3件に制限する。"""
        return v[-3:] if len(v) > 3 else v
```

**ルール:**
- すべてのフィールドに `Field(description=...)` を付ける（Structured Outputs のスキーマ記述に使用される）
- デフォルト値を持つフィールドには `default` または `default_factory` を明示する
- バリデーションロジックは `field_validator` で宣言的に記述する（手続き的なチェックを外部に書かない）
- イミュータブルなデータモデルには `model_config` で `frozen=True` を設定する（現在は `DailyEvent` のみが該当）。`CharacterState` のようにパイプライン中で `model_copy(update=...)` により頻繁に更新されるモデルでは frozen にしない

### 3.2 モデルの変更手順

`schemas.py` のモデルを変更する場合は、以下の手順を必ず守ること:

1. `.steering/` にタスクディレクトリを作成し、変更理由を `requirement.md` に記録する
2. `architecture.md` のデータスキーマセクションを先に更新する
3. `schemas.py` を変更する
4. 関連するプロンプトファイル（`prompts/`）がスキーマ変更に対応しているか確認する
5. `tests/test_schemas.py` を更新し、テストが通ることを確認する
6. 影響範囲（`actor.py`, `critic.py`, `pipeline.py`）の修正を行う
7. 全テストが通ることを確認する

---

## 4. Git 運用

### 4.1 ブランチ戦略

```
main
  └── feat/[機能名]         # 新機能開発
  └── fix/[バグ名]          # バグ修正
  └── refactor/[対象]       # リファクタリング
  └── docs/[ドキュメント名]  # ドキュメント更新
  └── prompt/[プロンプト名]  # プロンプト変更
```

**ルール:**
- `main` ブランチへの直接コミットは禁止
- 作業はトピックブランチで行い、Pull Request を通じてマージする
- ブランチ名はケバブケースで、`[種別]/[内容]` の形式にする
- 短命ブランチを推奨する（1つのタスクに1つのブランチ、マージ後は削除）

### 4.2 コミットメッセージ規約

Conventional Commits に従う:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

**type の一覧:**

| type | 用途 | 例 |
|---|---|---|
| `feat` | 新機能 | `feat(actor): Phase 1 状態遷移の実装` |
| `fix` | バグ修正 | `fix(critic): expected_delta の計算誤りを修正` |
| `refactor` | リファクタリング | `refactor(pipeline): リトライロジックを RetryManager に抽出` |
| `test` | テストの追加・修正 | `test(schemas): CharacterState のクランプテストを追加` |
| `docs` | ドキュメント | `docs(architecture): Self-Healing 設計セクションを追加` |
| `prompt` | プロンプト変更 | `prompt(critic): persona_deviation の採点基準を精緻化` |
| `chore` | 設定・ツール | `chore: ruff 設定を pyproject.toml に追加` |
| `ci` | CI/CD | `ci: GitHub Actions ワークフローを追加` |

**scope の一覧:**

| scope | 対象 |
|---|---|
| `actor` | `csdg/engine/actor.py` |
| `critic` | `csdg/engine/critic.py` |
| `pipeline` | `csdg/engine/pipeline.py` |
| `schemas` | `csdg/schemas.py` |
| `config` | `csdg/config.py` |
| `scenario` | `csdg/scenario.py` |
| `viz` | `csdg/visualization.py` |
| `prompts` | `prompts/` ディレクトリ全体 |
| `docs` | `docs/` ディレクトリ全体 |

**コミットメッセージのルール:**
- 1行目は50文字以内を目安とする
- 日本語で記述する（type と scope は英語）
- 「何をしたか」ではなく「何が変わるか」を書く
- body が必要な場合は空行を挟む

```
feat(actor): Phase 2 日記生成の実装

- Prompt_Generator.md のテンプレート展開を実装
- リトライ時の revision_instruction 注入に対応
- temperature パラメータの外部制御に対応
```

### 4.3 Pull Request 手順

1. **ブランチを作成する**
   ```bash
   git checkout -b feat/implement-actor
   ```

2. **`.steering/` に作業記録を作成する**
   ```bash
   mkdir -p .steering/20250115-implement-actor
   ```

3. **実装・テスト・ドキュメント更新を行う**

4. **ローカルでの確認**
   ```bash
   # テスト
   pytest tests/ -v

   # 型チェック
   mypy csdg/ --strict

   # リンター
   ruff check csdg/
   ruff format csdg/ --check
   ```

5. **コミット・プッシュ**
   ```bash
   git add .
   git commit -m "feat(actor): Phase 1 状態遷移の実装"
   git push origin feat/implement-actor
   ```

6. **Pull Request を作成する**
   - タイトル: コミットメッセージの1行目と同じ形式
   - 本文: `.steering/` の `requirement.md` と `design.md` の要約
   - レビュワー: 指定する（または自動割り当て）

7. **レビュー・修正・マージ**

### 4.4 Pull Request のテンプレート

```markdown
## 概要
<!-- 何を変更したか、なぜ変更したか -->

## 変更内容
<!-- 主要な変更点のリスト -->

## 関連ドキュメント
- `.steering/XXXXXXXX-タスク名/requirement.md`
- `.steering/XXXXXXXX-タスク名/design.md`

## テスト
- [ ] `pytest tests/ -v` が全件 Pass
- [ ] `mypy csdg/ --strict` がエラー 0
- [ ] `ruff check csdg/` がエラー 0

## チェックリスト
- [ ] `glossary.md` の用語と一致している
- [ ] 新規ファイルは `repository-structure.md` に反映した
- [ ] 影響を受けるドキュメントを更新した
- [ ] `.steering/` に作業記録を残した
```

---

## 5. テスト方針

### 5.1 テスト分類

| 分類 | 対象 | ツール | LLM API |
|---|---|---|---|
| 単体テスト | 個別モジュール（schemas, config, critic のロジック部分） | pytest | 不要 |
| モックテスト | Actor, Critic の LLM 呼び出し部分 | pytest + unittest.mock | モック |
| 統合テスト | パイプライン全体の正常系・異常系 | pytest | モック |
| E2Eテスト | パイプライン全体の実 API 呼び出し | pytest（手動実行） | 実 API |

### 5.2 テスト対象と観点

#### `test_schemas.py`

| テスト観点 | テストケース例 |
|---|---|
| 正常系 | 有効な値で `CharacterState` が生成できる |
| クランプ動作 | `fatigue=1.5` → `1.0` にクランプされる |
| クランプ動作 | `stress=-2.0` → `-1.0` にクランプされる |
| memory_buffer制限 | 4件の buffer → 末尾3件に切り詰められる |
| バリデーション失敗 | `event_type="invalid"` で `ValidationError` が発生する |
| シリアライズ | `model_dump_json()` → `model_validate_json()` の往復変換が成功する |
| Optional フィールド | `unresolved_issue=None` で正常に生成できる |

#### `test_critic.py`

| テスト観点 | テストケース例 |
|---|---|
| expected_delta 算出 | `emotional_impact=+0.6` → `stress=-0.27, motivation=+0.24, fatigue=-0.12` |
| deviation 算出 | 期待値と実際の差分が正しく計算される |
| Pass 判定 | 全スコア 3 以上 → `True` |
| Reject 判定 | `persona_deviation=2` → `False` |
| 境界値 | 全スコア `3` → `True`（ぎりぎり合格） |
| 境界値 | スコア `2, 3, 3` → `False`（1つでも3未満はReject） |

#### `test_pipeline.py`

| テスト観点 | テストケース例 |
|---|---|
| 正常系 | 7Day 全てが1回で Pass する場合のフロー |
| リトライ | Phase 3 で Reject → リトライで Pass する場合 |
| Temperature Decay | リトライ時に Temperature が区分線形 [0.70, 0.60, 0.45, 0.30] で減衰する |
| Best-of-N | 3回リトライしても全 Reject → 最高スコアのペアが選択される |
| Phase 1 フォールバック | バリデーションエラー3回 → 前日状態コピーが実行される |
| memory_buffer 管理 | Day 5 で memory_buffer が [Day2, Day3, Day4] になる |
| Dayスキップ | 予期しない例外 → 該当Dayがスキップされ、次Dayが実行される |
| パイプライン中断 | 連続3Day失敗 → 中断され、生成済み成果物が保存される |

### 5.3 テストの書き方

```python
import pytest
from csdg.schemas import CharacterState, DailyEvent

class TestCharacterStateClamp:
    """CharacterState の連続変数クランプのテスト。"""

    def test_clamp_upper_bound(self) -> None:
        """1.0を超える値は1.0にクランプされる。"""
        state = CharacterState(
            fatigue=1.5,
            motivation=0.0,
            stress=0.0,
            current_focus="test",
            growth_theme="test",
        )
        assert state.fatigue == 1.0

    def test_clamp_lower_bound(self) -> None:
        """-1.0未満の値は-1.0にクランプされる。"""
        state = CharacterState(
            fatigue=-2.0,
            motivation=0.0,
            stress=0.0,
            current_focus="test",
            growth_theme="test",
        )
        assert state.fatigue == 0.0  # fatigue は 0.0〜1.0

    @pytest.mark.parametrize("value,expected", [
        (-1.0, -1.0),
        (0.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (-0.5, -0.5),
    ])
    def test_clamp_within_range(self, value: float, expected: float) -> None:
        """範囲内の値はそのまま保持される。"""
        state = CharacterState(
            fatigue=value,
            motivation=0.0,
            stress=0.0,
            current_focus="test",
            growth_theme="test",
        )
        assert state.fatigue == expected
```

**テストの書き方ルール:**
- テストクラス名は `Test` + テスト対象 + テスト観点
- テストメソッド名は `test_` + テスト内容（スネークケース）
- docstring で「何をテストしているか」を1行で説明する
- Arrange-Act-Assert (AAA) パターンに従う
- パラメタライズを活用し、境界値を網羅する
- LLM API呼び出しは必ずモックする（E2Eテスト以外）

### 5.4 モック戦略

```python
from unittest.mock import AsyncMock, patch
from csdg.engine.llm_client import LLMClient

@pytest.fixture
def mock_llm_client() -> LLMClient:
    """LLM API をモックしたクライアント。"""
    client = AsyncMock(spec=LLMClient)

    # Phase 1: 正常な CharacterState を返す
    client.generate_structured.return_value = CharacterState(
        fatigue=0.1,
        motivation=0.3,
        stress=0.0,
        current_focus="テスト",
        growth_theme="テスト",
    )

    # Phase 2: 正常な日記テキストを返す
    client.generate_text.return_value = "わたしは今日、コードを書いた......のかもしれない。"

    return client
```

**モック戦略のルール:**
- `LLMClient` の抽象インターフェースに対してモックする（`AnthropicClient` の内部実装には依存しない）
- モックの戻り値はテストケースごとに設定する
- 異常系テストでは `side_effect` で例外を発生させる
- E2Eテストは `@pytest.mark.e2e` マーカーを付け、通常のテスト実行からは除外する

### 5.5 カバレッジ目標

| モジュール | 目標カバレッジ | 理由 |
|---|---|---|
| `schemas.py` | 95% 以上 | 全バリデーションルールの検証が必須 |
| `config.py` | 90% 以上 | 設定値の読み込みと変換 |
| `engine/critic.py`（ロジック部分） | 95% 以上 | expected_delta, deviation, judge は完全な単体テストが可能 |
| `engine/actor.py` | 80% 以上 | LLM呼び出し部分はモックテスト |
| `engine/pipeline.py` | 85% 以上 | リトライ・フォールバックの全パターンをカバー |
| `scenario.py` | 90% 以上 | バリデーションルールの検証 |
| `visualization.py` | 70% 以上 | グラフ生成の正常完了確認 |

### 5.6 テスト実行コマンド

```bash
# 全テスト実行
pytest tests/ -v

# カバレッジ付き
pytest tests/ -v --cov=csdg --cov-report=term-missing

# 特定のテストファイル
pytest tests/test_schemas.py -v

# 特定のテストクラス
pytest tests/test_schemas.py::TestCharacterStateClamp -v

# E2Eテスト（実API使用 — 手動実行のみ）
pytest tests/ -v -m e2e

# E2Eテストを除外（デフォルト）
pytest tests/ -v -m "not e2e"
```

---

## 6. リンター・フォーマッター設定

### 6.1 ruff 設定

`pyproject.toml` に以下を記述する:

```toml
[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "TCH",  # flake8-type-checking
    "RUF",  # ruff-specific rules
]
ignore = [
    "E501",   # line-length は ruff formatter に任せる
]

[tool.ruff.lint.isort]
known-first-party = ["csdg"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### 6.2 mypy 設定

```toml
[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = "matplotlib.*"
ignore_missing_imports = true
```

### 6.3 pytest 設定

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "e2e: End-to-End tests requiring real LLM API (deselect with '-m not e2e')",
]
asyncio_mode = "auto"
```

---

## 7. 依存関係管理

### 7.1 パッケージマネージャ

uv を使用する。pip は使用しない。

```bash
# 依存関係のインストール
uv sync

# パッケージの追加
uv add pydantic

# 開発用パッケージの追加
uv add --dev pytest mypy ruff

# ロックファイルの更新
uv lock
```

### 7.2 依存関係の分類

`pyproject.toml` で以下のように分類する:

```toml
[project]
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "anthropic>=0.30",
    "matplotlib>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "mypy>=1.10",
    "ruff>=0.5",
]
```

### 7.3 依存関係更新のルール

- 新しい依存を追加する前に、既存の依存で代替できないか検討する
- セキュリティアップデートは速やかに適用する
- メジャーバージョンアップは `.steering/` に影響調査を記録してから実施する
- `uv.lock` の変更は専用のコミット（`chore: uv.lock を更新`）で行う

---

## 8. セキュリティ方針

### 8.1 機密情報の管理

| 情報 | 管理方法 | Git管理 |
|---|---|---|
| LLM APIキー (Anthropic) | 環境変数 `CSDG_ANTHROPIC_API_KEY` | ✕ |
| LLM APIキー (Gemini) | 環境変数 `CSDG_GEMINI_API_KEY` | ✕ |
| `.env` ファイル | ローカルのみ。テンプレートとして `.env.example` をGit管理 | `.env` は ✕ / `.env.example` は ○ |
| 生成ログ | `output/generation_log.json` | ✕（APIキーが含まれないことを保証） |

### 8.2 出力のサニタイズ

`generation_log.json` にAPIキーやその他の機密情報が含まれないよう、出力前にサニタイズする。

```python
def sanitize_log(log: PipelineLog) -> PipelineLog:
    """ログから機密情報を除去する。"""
    # config 内の API キーをマスク
    sanitized = log.model_copy(deep=True)
    if hasattr(sanitized, 'config') and hasattr(sanitized.config, 'api_key'):
        sanitized.config.api_key = "***REDACTED***"
    return sanitized
```

### 8.3 プロンプトインジェクション対策

LLMへの入力に外部ユーザーの入力が含まれる場合（将来の拡張時）は、以下の対策を講じる:
- ユーザー入力はプロンプト内で明確にデリミタで区切る
- System Promptでインジェクション攻撃への耐性を指示する
- LLM出力のパース前にサニタイズする

**現時点のスコープ:** 本システムは外部ユーザー入力を受け付けないため、プロンプトインジェクションのリスクは低い。ただし、`scenario.py` の `description` フィールドは将来的に外部ソースから読み込む可能性があるため、バリデーションを厳格にしておく。

---

## 9. パフォーマンスガイドライン

### 9.1 API呼び出しの最適化

| 施策 | 内容 |
|---|---|
| トークン数の監視 | 各Phase のプロンプトトークン数をログに記録し、コンテキスト長制限に余裕を持たせる |
| 不要なリトライの削減 | プロンプトの品質向上により、1回で Pass する割合を高める |
| Temperature 設定 | 初回で高い Pass率を狙うため、Phase 3 の Critic には低い Temperature（0.3）を使用する |
| フォールバックの早期判断 | Best-of-N 選択時、明らかに低品質な候補は CriticScore の合計で早期に除外する |

### 9.2 メモリ使用量

| 施策 | 内容 |
|---|---|
| ストリーミング | 将来的に Phase 2 の生成をストリーミングに移行する場合、メモリに全文を保持しない設計にする |
| matplotlib | グラフ生成後にfigureを明示的に閉じる（`plt.close()`）|
| 大量ログ | `generation_log.json` が巨大になる場合、Day単位での分割出力を検討する |

---

## 10. 作業フロー

### 10.1 新機能追加の標準フロー

```
1. 要件の理解
   └─ functional-design.md の該当セクションを確認する
   └─ glossary.md で用語を確認する

2. 作業記録の開始
   └─ .steering/[YYYYMMDD]-[タスク名]/ を作成する
   └─ requirement.md, design.md, tasklist.md を記述する

3. ブランチの作成
   └─ git checkout -b feat/[機能名]

4. 実装
   └─ architecture.md と repository-structure.md に従ってファイルを配置する
   └─ コーディング規約（本ドキュメント §2）に従う

5. テスト
   └─ テスト方針（本ドキュメント §5）に従ってテストを作成する
   └─ pytest, mypy, ruff を実行する

6. ドキュメント更新
   └─ 影響を受けるドキュメントを更新する
   └─ repository-structure.md を更新する（ファイル追加時）

7. コミット・プッシュ
   └─ コミットメッセージ規約（本ドキュメント §4.2）に従う

8. Pull Request
   └─ PR テンプレート（本ドキュメント §4.4）に従う

9. レビュー・修正・マージ
   └─ レビュー指摘を反映する
   └─ .steering/ の tasklist.md を完了状態にする
```

### 10.2 バグ修正の標準フロー

```
1. バグの再現
   └─ 再現手順を確認する
   └─ 該当するテストケースを特定する（なければ作成する）

2. 作業記録の開始
   └─ .steering/[YYYYMMDD]-fix-[バグ名]/ を作成する

3. ブランチの作成
   └─ git checkout -b fix/[バグ名]

4. テストの追加
   └─ バグを再現するテストを先に書く（Red）

5. 修正の実装
   └─ テストが通るように修正する（Green）

6. リファクタリング
   └─ 必要に応じてコードを整理する（Refactor）

7. 全テスト実行
   └─ 修正がリグレッションを起こしていないことを確認する

8. コミット・PR・マージ
```

### 10.3 プロンプトチューニングの標準フロー

```
1. 問題の特定
   └─ generation_log.json から低スコアのDayを特定する
   └─ CriticScore の reject_reason を分析する

2. 作業記録の開始
   └─ .steering/[YYYYMMDD]-tune-[対象]/ を作成する

3. ブランチの作成
   └─ git checkout -b prompt/tune-[対象]

4. プロンプトの修正
   └─ prompts/ の該当ファイルを編集する
   └─ glossary.md の用語との一致を確認する
   └─ ペルソナの禁則事項が維持されていることを確認する

5. 検証
   └─ python -m csdg.main --day [対象Day] で再生成する
   └─ CriticScore の改善を確認する
   └─ 他のDayへの影響がないことを確認する（全Day実行）

6. 結果の記録
   └─ .steering/ の decisions.md にチューニングの結果と判断を記録する

7. コミット・PR・マージ
```

---

## 11. コードレビュー基準

### 11.1 レビュー観点チェックリスト

| カテゴリ | 確認項目 |
|---|---|
| **設計整合性** | `architecture.md` の設計方針に沿っているか |
| **設計整合性** | モジュール間の依存方向が正しいか（循環参照がないか） |
| **設計整合性** | `glossary.md` の用語を正しく使用しているか |
| **型安全性** | すべての関数に型アノテーションがあるか |
| **型安全性** | `Any` 型を使用していないか（使用する場合は理由があるか） |
| **型安全性** | `mypy --strict` でエラーがないか |
| **テスト** | 新規コードに対応するテストがあるか |
| **テスト** | 境界値テストが含まれているか |
| **テスト** | テストが実装の詳細に依存していないか |
| **エラー処理** | 例外が適切にハンドリングされているか |
| **エラー処理** | フォールバックが実装されているか（LLM呼び出し部分） |
| **プロンプト** | プロンプトがコードに埋め込まれていないか |
| **プロンプト** | プレースホルダが正しく使用されているか |
| **セキュリティ** | APIキーがハードコードされていないか |
| **セキュリティ** | ログに機密情報が含まれていないか |
| **可読性** | docstring が記述されているか |
| **可読性** | マジックナンバーが使用されていないか |
| **可読性** | 変数名が意味を伝えているか |
| **パフォーマンス** | 不要なAPI呼び出しがないか |
| **ドキュメント** | 影響を受けるドキュメントが更新されているか |

### 11.2 レビュー時のコミュニケーション

- 指摘は「提案」と「必須修正」を明確に区別する
  - `[nit]` — 些細な改善提案（対応は任意）
  - `[suggestion]` — 改善提案（検討を依頼）
  - `[must]` — 必須修正（マージブロッキング）
  - `[question]` — 設計意図の質問
- 良いコードには称賛を忘れない
- 代替案を提示する場合はコード例を添える
