# ADR-0012: Clang 18 の索引 API を分離した C++ アダプター

- 状態: 採用
- 日付: 2026-10-31
- 関連契約: `GRAPH-001`、`NAME-001`、`RELATION-001`、`LOCATION-001`、`DIAGNOSTIC-001`、`REFRESH-001`、`COMMAND-001`
- 実装: [cpp_indexer.py](../../script/indexers/cpp_indexer.py)
- 受入試験: [test_cpp_indexer.py](../../tests/modern_indexers/test_cpp_indexer.py)
- 人工対象・独立期待: [fixtures/cpp](../../tests/modern_indexers/fixtures/cpp/)、[expected.json](../../tests/modern_indexers/fixtures/cpp/expected.json)

## 背景と問題

既存の Clang 11 解析器は、既存索引との比較基準として保持する。新版の C++ を追加するために、GUI、SQLite、既存の C++ AST API の版依存をまとめて変更すると、意味の差と構造変更の差を識別しにくくなる。解析エンジンは別の固定環境で動かし、共通グラフの境界で検査する。

採用時に二つの反例を実測した。

1. 通常の libclang cursor 木の走査では、C++20 の `export` に包まれた宣言が `UNEXPOSED_DECL` となり、内部の関数や concept が見えない。一方、公式の `clang_indexTranslationUnit` の宣言・参照通知は、その宣言と呼び出しを返す。
2. Clang 18 は制約の異なる関数テンプレートへ同じ USR を返す場合がある。USR だけで統合すると、`Small` と `Large` に制約された二つの overload と、その異なる呼び出し先が一つになる。

構文を受理した事実だけで、必要な意味が抽出できたとは判断しない。これらの反例を受入試験へ残した。

## 決定

### エンジンと境界

固定した `modern` 環境の Clang / libclang **18.1.8** を使う。Python bindings は `libclang==18.1.1` の配布物を使い、実際の C ライブラリーは同じ環境の `libclang.so.13` を明示的に選ぶ。このファイル名の `13` は、エンジン版が 13 であるという意味ではない。起動時に `clang_getClangVersion` を読み、能力宣言へ実際の版を記録する。対応外の版は拒否する。

`cpp_indexer.py` は、設定とソースから `files`、`symbols`、`edges`、`diagnostics` を返す。SQLite の ID 割当てとトランザクションは [共通出力層](../../script/indexers/graph.py) が所有する。Clang 固有の ctypes 宣言、C API の寿命管理、例外の回収は一つの小さな境界へ集める。C のコールバック内で発生した例外を失わず、C API が戻った後に解析失敗として伝える。

### 名前と関係

- 通常の宣言・定義は Clang の USR でまとめる。名前階層には戻り型、引数型、CV・参照修飾等の署名を保持する。
- 関数テンプレートは canonical declaration の所在と完全なテンプレート宣言を併用し、制約付き overload を区別する。暗黙の実体化からの呼び出しは元のテンプレート宣言へ結び付ける。明示的な特殊化は独立した記号として保持し、`template_specialization` 関係を記録する。
- internal linkage の記号は翻訳単位の相対パスも区別する。同じ basename のファイルに同名の static 関数があっても統合しない。
- 呼び出しは Clang が通知する `Call` role を使い、通常の参照と区別する。継承、override、所属、型使用、include、macro 使用を別の関係に写す。
- concept は共通グラフの `type`、module は `module` へ写す。module 所有の記号は module 名を階層の先頭へ付ける。
- compiler が暗黙に生成した参照は通常のユーザー参照として追加しない。coroutine はユーザーが書いた関数・呼び出し・範囲を記録する。

### ビルド設定と modules

`compile_commands.json` の `directory`、引数、マクロ、include、target、sysroot を解析入力として扱う。`command` は引数列へ分解するだけで、シェルとして実行しない。出力先やコンパイルの出力動作は除き、ソースの意味に関係する引数を libclang へ渡す。相対ヘッダーは C API が返す実パスで正規化し、Python の作業ディレクトリーとの混同を避ける。

同じ翻訳単位に異なるコンパイル設定が複数ある場合は、黙って混ぜずに拒否する。利用者は比較対象の構成を選んだ compilation database を用意する。応答ファイルの循環、誤った設定、compiler plugin の読込みも拒否する。compilation database と応答ファイルは保存内容付きの `config` 入力として観測する。翻訳単位から設定入力へ `include` 依存を記録する。この関係は compiler が読み込む設定への依存を表す。ルート外の応答ファイルは非所有の依存ファイルとして保存し、内容変更から翻訳単位へ更新を伝える。同一・過去時刻での応答ファイル変更も検出する。

native 側が監視するソース・ヘッダー拡張子をアダプターの観測対象と揃える。CDB に選択されない `.cpp` や未使用ヘッダーも保存し、無変更時に新規入力として何度も再索引することを防ぐ。そのファイルの意味宣言は作成せず、`active=false`、`complete=false` と「観測したが選択構成では解析していない」という診断を返す。自動的な翻訳単位の探索では `build` と `node_modules` を除外するが、明示 CDB で選択された翻訳単位の解析と、native の監視対象を保存する処理は分離する。

C++20 modules は、module interface と、事前生成した BMI を使う import を対象にする。受入試験では同じ **18.1.8** の `clang++ --precompile` で BMI を作成し、実際に読み込ませる。18.1.8 の BMI を 18.1.1 のライブラリーへ渡した実験は読込失敗となったため、エンジンと BMI 生成器の patch 版を合わせる。アダプターは任意のビルドシステムを実行せず、BMI の自動再生成は行わない。ソース・設定を変更した場合は、その設定に対応する BMI を再生成する必要がある。

module/import 宣言自体には安定 C API の専用 cursor がないため、Clang のトークン列からトップレベルの名前と位置を写す。export 内の記号と参照の意味は、前述の索引 API が提供する。文字列検索だけで関数や参照を推測しない。

### 位置・診断・更新

アダプターの返却内容は UTF-8 の原文で、BOM、CRLF、最後の改行の有無を維持する。Clang の byte offset を共通の **1 始まり・終端込み UTF-8 バイト列**へ写す。宣言名の位置はトークン範囲、定義の範囲は source extent から求め、Unicode 上の診断範囲も完全な UTF-8 scalar を含める。CLI の原文照合後、共通出力層が CRLF を既存 DB の LF 規約へ正規化し、行末の範囲・診断位置も対応して移す。BOM と最後の改行の有無は保存される。

構文・意味診断は診断付きの不完全なファイルとして返す。起動・共有ライブラリー・C API・入力読込み・不正 BMI・出力写像の失敗は例外となり、呼出し側が候補を拒否できる。空の成功へ変換しない。取得した内容が解析後に変わっていれば拒否するが、これをファイルシステム全体の原子的取得とは主張しない。

更新はプロジェクト単位の全体解析を選ぶ。CDB が空配列で、最後のソースも削除済みである明示的な空構成は正常として扱い、CDB だけを入力へ残す。既存ソースがあるのに CDB が空、または CDB が削除済みの翻訳単位を指す場合は拒否する。CDB を使わない明示的な空入力は `allow_empty=true` で選択できる。

## 検証と保証範囲

人工対象の手書き期待に加え、旧 C++ トイの必要な定義、overload ごとの呼び出し、所属、include、正確な宣言名位置を、新版エンジンの結果へそのまま照合する。比較はその共通能力に限定し、旧版と新版の DB 全体が同一であるとは主張しない。

追加の受入試験は、concepts、制約付き overload、明示的特殊化、`consteval`、`if consteval`、designated initializer、generic lambda、実 coroutine、export、実 BMI import、override、macro 位置、Unicode、BOM、CRLF、CDB の cwd・引用符・マクロ、診断・修復、応答ファイル、空構成を扱う。[独立レビューの実アプリ試験](../../tests/modern_indexers/test_integration_review_e2e.py)では、CDB 未使用入力があっても無変更時に再索引しないこと、ルート外応答ファイルの同一時刻変更が反映されること、更新結果と全体再索引結果の同値性を検査する。実測値とコマンドの最終記録は統合レポートへ集約する。

これは固定された能力と入力の受入結果であり、C++20/23 規格全体、全標準ライブラリー、任意のビルドシステム、全 OS、巨大入力の性能の保証ではない。既存 Clang 11 の基準と別の能力プロファイルとして選択する。

## 一次資料

- [Clang 18.1.1 公開 C API 定義](https://github.com/llvm/llvm-project/blob/llvmorg-18.1.1/clang/include/clang-c/Index.h)
- [Clang: Indexing](https://clang.llvm.org/doxygen/group__CINDEX__HIGH.html)
- [Clang: Cross-referencing in the AST](https://clang.llvm.org/doxygen/group__CINDEX__CURSOR__XREF.html)
- [Clang: Standard C++ Modules](https://clang.llvm.org/docs/StandardCPlusPlusModules.html)
- [Clang C++ feature status](https://clang.llvm.org/cxx_status.html)
- [固定 Python bindings の配布元](https://pypi.org/project/libclang/18.1.1/)
