# ADR-0010: 今回の消去で使われなくなった組み込み型だけを回収する

- 状態: 採用
- 日付: 2026-10-31（Asia/Tokyo）
- 関連契約: `GRAPH-001`, `RELATION-001`, `STORAGE-002`, `INPUT-001`
- 関連判断: [ADR-0005](0005-toy-project-conformance.md)、[ADR-0008](0008-content-based-input-observations.md)

## 背景

ソースを空へ切り詰める入力観測では、更新結果を全体再構築と比較する。組み込み型 `int` にはユーザーソース上の宣言位置がないため、型を使う最後の関数を消しても、出現を入口とした従来の回収候補へ型が入らない。この場合、空入力のクリーン索引には存在しない型が更新後に残る。

## 決定

[SqliteIndexStorage::removeElementsWithLocationInFiles](../../src/lib/data/storage/sqlite/SqliteIndexStorage.cpp) で、辺を消す前に、今回消す出現または参照元から到達する `NODE_BUILTIN_TYPE` のIDだけを一時表へ保存する。通常の消去処理の後、その型に出現がなく、参照元・参照先のどちらの辺も残らない場合だけ削除する。

これは一般的な孤立ノードの回収へ変更するものではない。今回触れていない型は残し、別ファイルで使用している型と、辺または出現で保護される型を残す。既存の所属辺保持規則も維持する。数値IDや保存順ではなく、型・辺・出現の意味を比較する。

## 検証

[StorageCleanupContractTestSuite](../../src/test/StorageCleanupContractTestSuite.cpp) に最後の使用を削除する例と共有使用を残す例を置く。同時に、今回触れていない組み込み型を削除しないことも確認する。[入力観測のC++人工対象](../../tests/input_observation/test_input_observation.py)は、関数を含むソースから空内容への更新と全体再構築を比較する。

この限定修正は全関係種類の一般消去規則や、巨大入力の性能を保証しない。旧実装と異なる差は、不要な意味要素を取り除く意図した修正として扱う。
