# Rust 索引の人工対象

`shape-app` は `shapes` を利用する。`shapes` は `operations` module、`Square` 型、`Measure` trait、inherent impl と trait impl、再エクスポート `twice`、`macro_rules! identity`、Unicode 名の `計算` を持つ。

目的は Rust の全構文を網羅することではなく、名前解決を伴う最小の関係を独立した期待値で検査することである。`expected.json` の辺は人が対象ソースから定めた。解析出力から生成した期待値ではない。

| 操作・観測 | 必要な結果 |
| --- | --- |
| `run` 内の `square.measure()` | trait の宣言ではなく `impl Measure for Square` のメソッドへ CALL |
| `shapes::twice(2)` | 再エクスポート前の `operations::double` へ CALL |
| `Square` と `Measure` | 実装関係とメソッドの OVERRIDE |
| `計算` 内の `identity!` | MACRO_USAGE、呼出側の元ソース位置 |
| Unicode 名 | 保存した UTF-8 の6バイトが `計算` と一致 |
| feature なし／`shapes/extra` | `optional` の欠如／存在、別の構成識別 |
| cfg なし／`custom_mode` | `configured` の欠如／存在 |
| ソースを型エラーへ変更 | 元ソースの診断と `complete=false` |
| module を削除して代替関数を追加 | 古いファイル・記号が消え、別場所での全体再構築と一致 |
| BOM・CRLF・終端改行なし | 保存内容のバイト列保持と全位置の検査成功 |
| Unicode 終端を1バイト短く改変 | 共通グラフ検査が UTF-8 の分割として拒否 |

Cargo.lock を含め、通信不要のローカル二 crate で実行する。Rust 1.85.1、固定 rust-analyzer、標準ライブラリのソースは `modern` 環境と準備作業で供給する。実行はリポジトリのルートから `pixi run --locked -e modern python -m pytest tests/modern_indexers/test_rust_indexer.py` とする。

設計判断は [ADR-0013](../../../../docs/adr/0013-rust-source-indexer.md) を参照する。
