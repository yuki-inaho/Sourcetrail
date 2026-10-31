# 新版Python・C++・Rustの索引化

## 実装の入口

Python 3.14、Clang 18、Rust/Cargo 1.85.1とrust-analyzerを使う索引アダプターを追加した。アプリへはネイティブ設定型 **Modern Language Source Group** で接続する。従来のClang 11／旧Python解析器も保持している。

| 対象 | 実装 | 解析文脈・検証する能力 |
| --- | --- | --- |
| Python | [python_indexer.py](../../script/indexers/python_indexer.py) | Python 3.14構文、明示したsource roots、スコープ、import、継承、静的に確定できる呼出 |
| C++ | [cpp_indexer.py](../../script/indexers/cpp_indexer.py) | Clang 18.1.8 C索引API、compile_commands、引数とcwd、overload、concepts、coroutines、同版BMIのmodules |
| Rust | [rust_indexer.py](../../script/indexers/rust_indexer.py) | Cargo workspace、edition、features、target、rust-analyzer LSP、定義・参照・呼出・trait実装・診断 |
| 保存境界 | [graph.py](../../script/indexers/graph.py) | 名前・参照・位置・schema25の検査とSQLトランザクション |
| 起動・設定 | [cli.py](../../script/indexers/cli.py) | プロトコル・能力照合、入力競合の検出、設定生成 |

依存する実際のパッケージビルドは [pixi.lock](../../pixi.lock) に固定する。Rustの解析器と標準ライブラリーソースは [rust_runtime.py](../../script/indexers/rust_runtime.py) に版・配布URL・SHA-256を固定し、準備時に照合する。索引中にエンジンを自動取得しない。

## 利用手順

リポジトリ直下で `pixi install --locked --all` を実行し、`pixi run --locked -e modern prepare-rust-indexer` でRustエンジンを準備する。アプリは `pixi run --locked build` でビルドする。

設定生成は `pixi run --locked -e modern python -m script.indexers.cli configure` を使う。指定する引数は以下のとおり。

| 引数 | 内容 |
| --- | --- |
| `--language` | `python`、`cpp`、`rust` のいずれか |
| `--root` | ソース／Cargo workspace／compile_commandsの基準ディレクトリ |
| `--project` | 新しく作る `.srctrlprj` のパス。既存プロジェクトを上書きしない |
| `--options` | 任意。エンジン設定を持つJSONファイルのパス |

例えばPythonなら `--language python --root /path/to/source --project /path/to/project.srctrlprj` を上記設定生成コマンドへ渡す。生成されたプロジェクトはGUIで開くか、`build/pixi/app/Sourcetrail index --full /path/to/project.srctrlprj` で解析する。次回以降の更新では `--full` を省略する。

一つのModernグループは全体を一回で解析する。入力変更があればグループ全体を再構築するため、削除した記号や古い構成が残らない。設定生成後に実行環境やリポジトリを移動した場合は、明示された実行ファイルパスを新しい場所へ更新する。root、source_roots、CDBのパスなど入力の所属範囲を変える場合は、新しいプロジェクト名で設定を再生成する。`.srctrlcfg` とネイティブ側のsource_pathsを異なる範囲にした設定は対応プロファイルに含めない。旧Pythonの索引DBには位置規約の自動判別を行わないため、移行時には全体再索引化が必要である。

## 設定と対応範囲

### Python

`source_roots` はrootからの相対パス一覧で、各ディレクトリをimportの基準とする。既定はroot自身。namespace packageや相対importを扱う。動的importや一般の型推論は行わず、解決できない呼出を診断として残す。解析するコードを実行しない。

pattern matching、例外グループ、型パラメーター、型エイリアス、テンプレート文字列を含む人工対象がある。旧版との共通能力は別の実アプリ試験で確認する。Python言語全体の実行意味や、Jediの全推論能力を保証するものではない。

### C++

`compilation_database` は既定で `compile_commands.json`。`directory`、`arguments`／`command`、マクロ、include、target、sysroot、応答ファイルを解析文脈として扱う。コンパイルコマンド自体を実行しない。CDBなしの小対象には `standard` と明示した追加引数を利用できる。複数の異なる構成が同じ翻訳単位へ割り当てられた場合は拒否し、構成を分けて解析する。

modulesのimportには、同じClang 18.1.8で作成したBMIと対応するコンパイル引数が必要である。export内の宣言を見落とさないよう、単純なcursor走査ではなくClangのC索引APIを使う。concepts、coroutines、C++23の個別構文を受入対象にするが、C++20／23の規格全体の適合宣言ではない。[ADR-0012](../adr/0012-modern-cpp-indexer.md)

### Rust

rootはCargo workspace。`features`、`all_features`、`no_default_features`、`target`等は明示的な設定とし、構成を記号の同一性へ反映する。Cargo.toml／Cargo.lockも観測対象になる。別crateへの呼出、traitとimpl、実装メソッド、module依存、マクロ呼出元を人工対象で確認する。

索引前に有効なCargo.lockと依存キャッシュを準備する。既定の索引処理ではCargoを`--locked --offline`で呼び、lockファイルを生成・更新しない。新しい依存を追加した場合は通常のCargoによる準備を済ませてから再索引化する。準備済み標準ライブラリー用キャッシュ以外を使う場合は、アダプターの明示した`cargo_home`設定を指定する。同キャッシュにも標準ライブラリーの固定依存が必要であり、`bin/cargo`があるキャッシュは内部実行の版固定を保証できないため拒否する。

定義・参照・呼出はrust-analyzerの意味問い合わせを利用し、コンパイラーのJSON診断を保存する。手続きマクロの展開を完全対応とはせず、未対応の設定を拒否する。生成コードの位置を元ソースの位置として捏造しない。[ADR-0013](../adr/0013-rust-source-indexer.md)

## 位置と不完全な結果

エンジン出力は生UTF-8に対応させ、保存時には既存のLF規約へ揃える。BOMを含む列、最終改行の有無、CRLF、Unicodeを検証する。保存列は1始まり、UTF-8バイト、終端込みである。新版アダプターで単独CRの改行は拒否する。

構文診断がある場合は不完全なファイルとして保存できる。プロトコル不一致、壊れた出力、入力内容の競合などは実行失敗となり、アプリは候補を採用しない。修復後に再実行できる。任意の外部Customコマンドへこの出力検査が自動適用されるわけではない。

## 人工対象・検証

| 題材 | 独立した期待と観測 |
| --- | --- |
| Python新構文・Unicode・import | 定義種別、静的呼出先、継承、実トークンのバイト位置、実行禁止の確認 |
| C++新構文・CDB・modules | overload/制約付きtemplateの区別、実coroutine、BMIを作って実import、設定差・不正BMIの拒否 |
| Rust workspace | crate間呼出、trait/implの区別、featuresで有効な記号だけ出力、UTF-8位置、診断、変更・削除 |
| 共通保存の負例 | 不正UTF-8境界、参照先欠落、同一性衝突、未知のDB版、異なる所有者の内容、rollback |
| 実アプリ | 初回、無変更、同一mtimeの編集、削除、空化、clean再構築、失敗時保持、修復後再実行 |

入口は [tests/modern_indexers](../../tests/modern_indexers/) と [tests/input_observation](../../tests/input_observation/)。`pixi run --locked verify` は従来の全検証に加え、新しい言語の試験も実行する。言語ごとの単体試験だけの成功で実アプリ統合を合格扱いしない。Linux x86_64のCLIを実測対象とし、実GUI操作やWindows/macOSの実測とは区別する。
