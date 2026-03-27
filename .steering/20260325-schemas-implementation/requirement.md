# 要件定義: schemas-implementation

## 背景
CSDG パイプラインの基盤となる Pydantic データモデルを実装する。
`docs/architecture.md` §2, §3 および `docs/glossary.md` §2 で定義された5つのモデルを
`csdg/schemas.py` に実装し、型安全性とバリデーションを保証する。

## 実装内容
1. **DailyEvent** — 日次イベント（frozen, 厳密バリデーション）
2. **CharacterState** — キャラクター内部状態（連続変数クランプ, memory_buffer制限）
3. **CriticScore** — 評価器スコア（スコア範囲チェック, Reject時必須フィールド検証）
4. **GenerationRecord** — 1Dayの生成記録
5. **PipelineLog** — パイプライン全体ログ

## 受け入れ条件
- [ ] 5つのモデルが定義されている
- [ ] 全フィールドに `Field(description=...)` がある
- [ ] `field_validator` でクランプ・バリデーションが実装されている
- [ ] テストが全件 Pass
- [ ] mypy --strict がエラー 0
- [ ] ruff check がエラー 0

## 影響範囲
- `csdg/schemas.py` — 新規作成
- `tests/test_schemas.py` — 新規作成
