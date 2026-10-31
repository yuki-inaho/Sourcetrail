# ADR-0013: Cargo 構成を固定し、rust-analyzer の意味情報を共通索引へ変換する

- 状態: 採用。固定した Rust 1.85.1／edition 2024 を含む人工対象で検証する範囲。
- 日付: 2026-10-31（Asia/Tokyo）
- 関連判断: [ADR-0004](0004-language-capabilities.md)、[ADR-0006](0006-portable-refresh-core.md)、[ADR-0007](0007-external-indexer-outcomes.md)
- 関連契約: `GRAPH-001`, `NAME-001`, `RELATION-001`, `LOCATION-001`, `DIAGNOSTIC-001`, `EXECUTION-001`, `VERIFICATION-001`

## 背景

既存の Rust 実装は更新計画コアの参照移植であり、Rust ソースから定義・参照・呼び出しを抽出する実装ではなかった。Rust の同名メソッド、trait の実装、再エクスポート、Cargo feature による宣言の有効／無効を、綴りの照合だけで正しく判定することもできない。

新しいアダプターは [rust_indexer.py](../../script/indexers/rust_indexer.py) に置き、実際の rust-analyzer に意味問い合わせを行う。プロセス通信、Rust の写像、共通グラフの検査・保存を分離し、既存 C++ の型や SQLite の ID を解析エンジンへ渡さない。

## 決定

### 固定エンジンと再現可能な準備

解析エンジンは rust-analyzer の `2025-03-03` 配布、自己申告版は `0.3.2328-standalone (81ff38f53b 2025-03-02)` とする。コンパイラー、Cargo、標準ライブラリのソースは Rust `1.85.1` と一致させる。Python は通信と変換を担当し、追加の Python パッケージを必要としない。

[rust_runtime.py](../../script/indexers/rust_runtime.py) は、公式アーカイブと展開後バイナリーの SHA-256 を検査してから配置する。配置済みの実行環境は、新しい候補の取得・検査が成功するまで置き換えない。索引処理がエンジンを自動取得することはなく、準備は独立した作業として行う。

標準ライブラリはソースだけでなく、その Cargo.lock に固定された依存も準備する。専用の Cargo キャッシュへ取得し、索引時には通信を行わずに標準ライブラリのメタデータを取得できることを確認する。固定エンジンの実装と同様、標準ライブラリ固有の manifest を読むときだけ bootstrap 設定を使い、利用者のコードをコンパイルする際には引き継がない。

| 対象 | 固定した SHA-256 |
| --- | --- |
| rust-analyzer gzip | `6cf40211f9755c63ac2f8f5fbeb4370d124aae7b1b082d501669b83e607762be` |
| rust-analyzer 展開後 | `d8bad3d2b4dc2d500ddbbe3842ab001b4f1ec353719164897b00a7f823e9a8ce` |
| Rust 標準ライブラリソース | `b5a5539009d477a07c2535aefc39cd69ad526a74eab65886a26e2c3021020827` |

索引開始時にもエンジンとコンパイラーの版を照合する。版、Cargo 構成、必要なプロトコル能力が対応外の場合は失敗として返し、空の成功結果へ変換しない。

### Cargo の構成を入力と同一性の一部にする

`cargo metadata --format-version 1 --locked` でワークスペースとパッケージを取得する。既定は通信を行わない設定とし、Cargo の子呼び出しにも `CARGO_NET_OFFLINE=true` を渡す。依存が未取得の場合は、完全な名前解決を装う代わりに明示的に失敗する。

固定エンジンの内部 `cargo metadata` は `cargo.extraArgs` の `--locked` を無視するため、内部 Cargo も専用の一時ラッパーで実行し、metadata に `--locked` を補う。これにより Cargo.lock の余分な末尾空行も勝手に正規化しない。既存の Cargo キャッシュを明示する場合は、エンジンが環境指定より優先する `bin/cargo` の rustup プロキシを含まないものを使う。準備タスクの専用キャッシュはこの条件を満たす。プロキシがある構成は、固定実行先と lock の保証が成立しないため拒否する。

`features`、`all_features`、`no_default_features`、`cfg`、`target`、`all_targets` を、コンパイラーと rust-analyzer の両方へ渡す。追加のコンパイラー引数、対象設定、`.cargo/config.toml` の内容も構成識別へ含める。rust-analyzer が既定で追加する `cfg(miri)` を無条件に採用しない。

対象 triple は明示オプション、`CARGO_BUILD_TARGET`、ワークスペースの `.cargo/config` または `.cargo/config.toml` の `build.target` の順に選び、コンパイラーとエンジンで揃える。Cargo と同じく旧名 `config` があれば優先する。どちらの設定ファイルも観測入力として保持する。複数対象の一括指定と、別の JSON ファイルを入力とするカスタム対象はこのプロファイルでは拒否し、構成ごとに一つの triple を指定する。

名前階層には crate 名、パッケージ名と版、対象の種別、edition、構成識別を持たせる。識別子だけを分離しても schema 25 の保存名が衝突するため、保存する名前階層にも構成の区別を残す。別構成の同名記号を一つへ統合しない。ローカル変数は宣言位置で区別し、複数の同じ inherent impl は同じ実装コンテナーにまとめ、出現位置を保持する。

Cargo.toml、Cargo.lock、設定・toolchain ファイルも保存対象とする。Rust ソースは UTF-8 の生内容を保持し、BOM、CRLF、最終改行を読み込み時に書き換えない。解析終了時には読み始めたソース内容と照合し、途中で変わった入力をそのまま公開しない。

アプリが列挙する `.rs`、`.toml`、`.lock` を観測入力として保存する。Cargo の有効な crate に属さない `.rs` は `parentModule` で区別し、変更検出用の内容を保持するが定義・辺を生成しない。除外するディレクトリはアプリと同じ `.git`、`.pixi`、`.venv`、`venv`、`target`、`__pycache__` に揃える。その他の隠しファイルを一括で落とさない。`cfg(test)` は `all_targets` と一致させ、エンジンの既定値を無条件には使わない。

### 意味情報の取得と共通グラフへの写像

[rust_lsp.py](../../script/indexers/rust_lsp.py) が JSON-RPC の入出力、要求の期限、通知、終了と子プロセスの回収を担当する。UTF-8 の位置を交渉し、他の座標単位しか返せないエンジンは拒否する。標準エラーを同時に読み、出力用パイプが満杯になって停止する経路を避ける。

| Rust の情報 | 取得・検査 | 共通グラフ |
| --- | --- | --- |
| 定義と範囲 | `documentSymbol` と `definition` の照合 | 種類、名前・署名、明示定義、トークンとスコープ位置 |
| 有効な宣言 | 宣言位置が意味解析でも定義へ解決すること | `cfg` で無効な宣言を除外 |
| 参照 | `references` | 使用、型使用、マクロ使用の辺と元ソース位置 |
| 呼び出し | `prepareCallHierarchy` と `outgoingCalls` | 呼び出し元から解決先への CALL 辺 |
| module、他ファイルの使用 | module の解決先と意味参照 | ファイル間の IMPORT 依存 |
| trait | interface ノード | 宣言された trait と所属メソッド |
| trait impl | `implementation` と実装対象型の定義解決 | 型から trait への INHERITANCE、実装コンテナーと所属 |
| trait メソッド実装 | `implementation` の具体的なメソッド位置 | 実装から宣言への OVERRIDE |
| `macro_rules!` | macro の意味分類と使用元 | MACRO／MACRO_USAGE と呼出側の元位置 |
| 外部定義 | 呼び出し階層の対象と宣言位置 | 定義なしの外部記号。存在しない作業領域の位置は付けない |

Rust における INHERITANCE の写像は「この型が trait を実装する」を意味する。C++ のクラス継承やサブタイプ関係と同一の言語意味を主張するものではない。interface ノード、実装コンテナー、OVERRIDE と組み合わせて区別する。

再エクスポートされた名前からの呼び出しも、実体の定義へ解決する。呼び出し先の同定に無修飾の文字列照合を使わない。展開後だけに存在する対象について、元ソースに存在しないトークン位置を作らない。エンジンが呼び出し階層を返さないマクロ展開内の参照は、確認できる使用関係として保持し、CALL と推測しない。

参照辺の受入範囲は選択したワークスペースの定義である。外部への呼び出しは定義なしの対象として記録するが、依存ライブラリのソースグラフ全体は取り込まない。ワークスペース外の module を直接読み込む構成は、入力の観測範囲が一致しないため拒否する。

### 座標・診断・失敗

LSP の 0 始まり・終端を含まない UTF-8 位置を、共通の 1 始まり・終端込み UTF-8 バイト位置へ変換する。次行の列 0 で終わる範囲は前行の実内容末尾へ写し、改行記号をトークンに混ぜない。保存直前には共通の [graph.py](../../script/indexers/graph.py) が UTF-8 文字の途中や範囲外の位置を拒否する。

アダプターから共通層へ渡す内容は物理ファイルのままとする。既存アプリの LF 保存規約への CRLF 変換は共通層が一度だけ行い、Rust 側で重ねて変換しない。

構文・型エラーは `cargo check --workspace --message-format=json` の元ソースへ写せる診断として保持する。意味解析の未解決参照も診断として残す。エラーを持つ Cargo 構成のファイルは、完全な索引とせず `complete=false` とする。警告、ソース診断、エンジン起動失敗は別の状態として扱う。

現プロファイルでは build script と procedural macro の完全な生成元対応を宣言しない。選択した依存構成にそれらが必要なら、索引全体を明示的に拒否する。失敗は既存の外部実行結果の境界に渡り、以前の採用済み索引を空の結果で置き換えない。

## 人工対象と受入条件

[人工 Cargo workspace](../../tests/modern_indexers/fixtures/rust/) は、ライブラリと利用側の二つの crate、別ファイルの module、再エクスポート、同名の trait／impl メソッド、構造体の生成、Unicode 名、マクロ、feature／cfg による追加宣言を持つ。[expected.json](../../tests/modern_indexers/fixtures/rust/expected.json) は必要な定義と辺を手書きした期待値であり、生成結果をそのまま正解にしていない。

[検証](../../tests/modern_indexers/test_rust_indexer.py) では、必要な定義・辺、具体的な呼出先、マクロ使用、UTF-8 のトークン内容、Cargo 設定入力、feature／cfg と名前同一性、エラー時の不完全性を確認する。変更と削除後の索引を別ディレクトリのクリーン再構築と比較し、古い記号・ファイルが残らないことも確認する。BOM・CRLF・最終改行なしの入力と、UTF-8 終端を故意に壊す負例を別に用意する。

標準ライブラリの `std::mem::size_of` への実呼び出しも確認する。ソースだけを置いた初期状態では、依存不足によりこの参照が未解決になる負例を得たため、上記の準備と事前検査を追加した。さらに不正な通信ヘッダー、未対応の UTF-16 応答、無応答の実プロセスを起動し、失敗として返してプロセスを回収すること、取得失敗で配置済みエンジンを失わないことを確認する。

観測入力を広げた試験では、エンジン内部の metadata が Cargo.lock を書き換える負例も再現した。入力照合がこれを拒否することを確認し、内部呼び出しの lock 固定を追加した。Cargo 対象外の Rust ファイル、隠しファイル、設定ファイルも観測し、対象外の定義・未解決参照を有効な crate の結果へ混ぜず、無変更の再実行が同一のグラフになることを確認する。

実アプリへの組込みと候補索引の採用は共通の Modern Source Group が担当する。Rust 単体の試験だけを、GUI、全 OS、任意規模の性能、クラッシュ時の公開原子性の保証へ広げない。部分消去の適合を宣言せず、構成単位で全体を再索引化する。

## 参照資料

- [rust-analyzer 公式配布 2025-03-03](https://github.com/rust-lang/rust-analyzer/releases/tag/2025-03-03)
- [固定エンジンの標準ライブラリ読み込み](https://github.com/rust-lang/rust-analyzer/blob/2025-03-03/crates/project-model/src/sysroot.rs)
- [固定エンジンの Cargo metadata 引数](https://github.com/rust-lang/rust-analyzer/blob/2025-03-03/crates/project-model/src/cargo_workspace.rs)
- [固定エンジンのツール実行先の選択](https://github.com/rust-lang/rust-analyzer/blob/2025-03-03/crates/toolchain/src/lib.rs)
- [rust-analyzer の設定](https://rust-analyzer.github.io/book/configuration.html)
- [Language Server Protocol 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
- [Cargo metadata](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html)
- [Cargo check](https://doc.rust-lang.org/cargo/commands/cargo-check.html)
- [rustc の JSON 診断](https://doc.rust-lang.org/rustc/json.html)

資料は API と構成の根拠であり、本アダプターの実行成功の代わりにはしない。実行証跡は現在のツリーの試験結果と統合レポートへ残す。
