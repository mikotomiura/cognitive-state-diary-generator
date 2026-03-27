# タスクリスト: schemas-implementation

## 実装タスク
- [x] DailyEvent モデルの実装
- [x] CharacterState モデルの実装
- [x] CriticScore モデルの実装
- [x] GenerationRecord モデルの実装
- [x] PipelineLog モデルの実装

## テストタスク
- [x] CharacterState クランプテスト
- [x] CharacterState memory_buffer サイズ制限テスト
- [x] DailyEvent バリデーションテスト
- [x] CriticScore スコア範囲・Reject必須フィールドテスト
- [x] JSON 往復変換テスト

## 検証タスク
- [x] pytest tests/test_schemas.py -v が全件 Pass (75 passed)
- [x] mypy csdg/schemas.py --strict がエラー 0
- [x] ruff check csdg/schemas.py がエラー 0
