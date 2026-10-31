# 言語互換性・解析エンジンの境界

更新日: 2026-10-31（Asia/Tokyo）。新しい解析器の利用手順は [modern-indexers.md](modern-indexers.md)、固定された対応能力は [language-profiles.json](../contracts/language-profiles.json) を参照する。

## 三つのバージョン軸

| 軸 | 意味 | 今回の区別 |
| --- | --- | --- |
| アプリの実行・ビルド環境 | Sourcetrail、試験ランナー、補助ツール | 従来のdefault環境はPython 3.11・Clang 11を維持 |
| 解析エンジン | Clang、旧Jedi、新ast、rust-analyzer | 新しいエンジンはmodern環境に分離し、版を固定 |
| 対象コードの意味 | 構文版、C++標準・ビルド設定、Rust edition・features・target | 機能別の人工対象と明示した設定で判定 |

ビルド用GCCの更新やpytestの実行版だけを根拠に、新しい対象構文へ対応したと判断しない。

## 実装済みの経路と限界

| 対象 | 実装経路 | 受入範囲 | 残る境界 |
| --- | --- | --- | --- |
| 従来C/C++ | 内部Clang 11 → ParserClient → 中間結果 | 既存回帰・人工対象・更新試験 | C++20/23の一般対応を旧プロファイルへ追加しない |
| 従来Python | 固定外部バイナリー → 位置変換 → 名前解決後処理 | 旧Python 3.8環境、UTF-8位置、更新・異常出力 | 新しいPython構文は新アダプターを選ぶ |
| Python 3.14 | ast → スコープ解析 → 共通グラフ | 新構文、import、定義・継承・静的に解決できる呼出 | 一般の型推論や動的importは未解決として診断 |
| C++20/23 | Clang 18.1.8 C索引API → 共通グラフ | CDB、overload、concepts、coroutines、同版BMIのmodules | 規格全体、任意のビルド構成の保証ではない |
| Rust | Cargo + rust-analyzer LSP → 共通グラフ | 小workspace、crate間参照・呼出、trait/impl、features、診断 | proc-macro/build.rs依存構成を明示拒否、全targetは未実測 |
| Java | 既存内部言語パッケージ | ソースを保持 | 基準PixiビルドではOFF |
| 任意のCustom | 既存外部コマンド → 作業DB | 起動・非ゼロ終了の失敗保持 | 一般の出力プロトコル、タイムアウト、取消は別課題 |

## 実装したアダプター契約

[ADR-0011](../adr/0011-modern-language-adapters.md)に従い、解析と保存を分ける。各エンジンは版付きのファイル・記号・辺・診断を返し、[共通検査と保存](../../script/indexers/graph.py)が名前衝突、参照先欠落、UTF-8境界、DB版を検査する。

| 項目 | 実装した扱い |
| --- | --- |
| 識別と版 | protocol_version=1、database_version=25、エンジン版、位置単位を起動時に照合 |
| 対象文脈 | Python source roots、CDBのcwd/引数、Cargoの構成をエンジンへ渡す |
| 同一性 | 名前階層と署名を保持。C++の制約付きtemplate、Rustのcrate/構成を区別 |
| 不完全性 | 構文診断とプロセス異常を区別。未解決を推測した解決済み関係へ変えない |
| 位置 | 生UTF-8の入力観測から、LF保存・1始まり・終端込みバイト位置へ変換 |
| 更新 | 部分消去を許可せず、変更のあるModernグループを一回で全体再構築 |
| 失敗 | 未対応版・壊れた出力は非ゼロ終了。既存の終了処理で失敗候補を不採用 |

[INPUT-001](../contracts/input-observations.md)により、索引済みファイルはmtimeが同一・過去でも保存内容との差で更新する。旧Pythonだけは文字位置からバイト位置へ変換する。既にバイト位置を出す新アダプターへ二重変換しない。

`Modern Language Source Group` は専用のネイティブ設定型として読み書き・表示するが、外部実行・コマンド構築の実装はCustomと共通化する。新たなIPC列挙や独自DBスキーマを不要にし、外部エンジンを更新可能な境界へ閉じ込める。

## 同等性と意図した差

旧版との共通の定義・呼出・継承・位置は手書き期待値と実アプリの観測で確認する。別プロファイルに追加される型パラメーター、ローカル束縛、trait/impl等を旧DB全体との厳密一致へ押し込めない。比較する共通能力と、新能力の期待を分ける。

旧Pythonのスコープ終端とUnicode列は、保存内容に対応する正規位置へ意図的に修正する。過去の文字列列座標を含むスナップショットとの無条件一致を合格条件にしない。一方、同じ新プロファイルの増分更新と全体再構築は、[schema25の厳密比較](../contracts/README.md)を通す。

Rust内部への値処理の参照移植と、今回のRustソース索引器は別の成果である。前者は [ADR-0006](../adr/0006-portable-refresh-core.md)、後者は [ADR-0013](../adr/0013-rust-source-indexer.md)で追跡する。

## 継続する受入範囲

アプリ公開処理のクラッシュ原子性、実GUI操作、全OS、一般のCustom出力検査、任意の巨大入力での性能は、新解析器の人工対象の成功から保証しない。[改善計画](evolution-plan.md)に契約ごとの状態を残す。

一次資料は [Python ast](https://docs.python.org/3.14/library/ast.html)、[Clang C++ status](https://clang.llvm.org/cxx_status.html)、[libclang索引API](https://clang.llvm.org/doxygen/group__CINDEX__HIGH.html)、[Cargo metadata](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html)、[rust-analyzer設計](https://rust-analyzer.github.io/book/contributing/architecture.html)。実際の採用版は固定依存と実行結果に従い、「最新」という語を能力契約の版指定にしない。
