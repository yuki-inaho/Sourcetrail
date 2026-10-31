# 設計判断記録 / ADR

ADR は「何を選んだか」だけでなく、「何を守り、何を今回保証しないか」を記録する。内部仕様の入口は [architecture/overview.md](../architecture/overview.md)、契約の機械可読な一覧は [contracts/catalog.json](../contracts/catalog.json) を参照する。

| ID | 判断 | 状態 | 日付 |
| --- | --- | --- | --- |
| [ADR-0001](0001-semantic-observations.md) | 観測プロファイルによって意味の同等性を定義する | 採用 | 2026-10-30 |
| [ADR-0002](0002-pure-refresh-planning.md) | 更新計画の集合演算を独立した境界へ抽出する | 採用 | 2026-10-30 |
| [ADR-0003](0003-bounded-formal-verification.md) | 有限の形式モデルと実装の適合試験を組み合わせる | 採用 | 2026-10-30 |
| [ADR-0004](0004-language-capabilities.md) | 言語名から独立した対応能力と解析器の版を管理する | 方針を採用、拡張 API は提案 | 2026-10-30 |
| [ADR-0005](0005-toy-project-conformance.md) | 人工的な小規模対象を独立期待と変更前後の実索引結果で確認する | 採用 | 2026-10-30 |
| [ADR-0006](0006-portable-refresh-core.md) | 可搬な値処理と既存アダプターを分離する | 採用 | 2026-10-30 |
| [ADR-0007](0007-external-indexer-outcomes.md) | 外部実行結果を集約し、失敗した候補索引を採用しない | 起動・非ゼロ終了の範囲で採用 | 2026-10-30 |
| [ADR-0008](0008-content-based-input-observations.md) | 時刻に依存しない入力内容の観測 | 採用・再実装 | 2026-10-31 |
| [ADR-0009](0009-canonical-python-source-positions.md) | 旧Pythonの文字位置を保存UTF-8バイト位置へ変換 | 採用・再実装 | 2026-10-31 |
| [ADR-0010](0010-clearing-unused-builtin-types.md) | 空化で残る組み込み型を限定的に回収 | 採用・再実装 | 2026-10-31 |
| [ADR-0011](0011-modern-language-adapters.md) | 版付きグラフとプロジェクト単位の新解析器、Python 3.14 | 採用 | 2026-10-31 |
| [ADR-0012](0012-modern-cpp-indexer.md) | Clang 18 C索引APIで新版C++を解析 | 採用 | 2026-10-31 |
| [ADR-0013](0013-rust-source-indexer.md) | Cargo文脈とrust-analyzerによるRustソース索引 | 採用 | 2026-10-31 |

## 変更時の規則

既存の判断を覆す場合は、元の記録を消さず新しい ADR から「置き換える」と参照する。各 ADR に背景、決定、代替案、影響、検証方法、未達成事項を含める。一般論だけの記録にせず、コード・契約 ID・試験・レポートへの接続を残す。

「採用」は記載した範囲の判断が有効であることを意味する。将来の言語アダプターや障害復旧機構が既に実装されたことを意味しない。
