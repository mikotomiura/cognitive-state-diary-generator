# 設計: schemas-implementation

## 実装アプローチ
- `pydantic-patterns/SKILL.md` と `validation-recipes.md` のパターンに厳密に従う
- 連続変数は `field_validator` でクランプ（エラーにしない）
- CriticScore のスコアは `field_validator` で厳密チェック（範囲外はエラー）
- CriticScore の Reject 判定は `model_validator(mode="after")` で実装
- DailyEvent は `model_config = {"frozen": True}` でイミュータブル

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/schemas.py` | 5つの Pydantic モデルを新規定義 |
| `tests/test_schemas.py` | 全モデルのバリデーション・境界値・往復変換テスト |

## 代替案と選定理由
- **event_type の型:** `Literal["positive", "negative", "neutral"]` も候補だが、`validation-recipes.md` に従い `field_validator` で実装し、エラーメッセージをカスタマイズ可能にする
- **CriticScore のスコア型:** `int` + `field_validator` を採用。`conint(ge=1, le=5)` も候補だが、mypy strict との相性と明示性から `field_validator` を選択
