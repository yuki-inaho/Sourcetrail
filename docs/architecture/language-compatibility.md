# 言語互換性・新バージョン・Rust の拡張設計

調査日: 2026-10-30。以下は**対応済みの宣伝用一覧ではなく、現行実装・検証範囲・追加に必要な条件の一覧**である。実際に解決する依存版は [pixi.lock](../../pixi.lock)、利用方法は [pixi-development.md](../pixi-development.md) を参照する。

## 三つのバージョン軸

| 軸 | 意味 | 取り違えた場合の誤り |
| --- | --- | --- |
| ツールの実行・ビルド環境 | Sourcetrail、試験ランナー、補助ツールを動かす版 | pytest を Python 3.11 で動かせたので Python 3.11 構文を索引化できると考える |
| 解析エンジン | Clang、Jedi／parso、将来の Rust 解析エンジン等 | ビルド用 GCC の更新だけで、埋め込み Clang の理解する C++ が変わると考える |
| 対象コードの意味 | Python の構文版、C++ 標準とビルド設定、Rust edition・features・target | 言語名だけ同じならどのコードも同じ設定で解析できると考える |

現行 CMake は基本のビルド標準を C++17 とし、C++ 言語パッケージの設定中は C++14 に切り替える箇所がある。これは**解析対象コードの C++ 標準とは別**である。[CMakeLists.txt](../../CMakeLists.txt)

## 現行の対応経路と検証上の境界

| 対象 | 現在の経路 | 現在の基準環境・観測 | 未達成／未検証 |
| --- | --- | --- | --- |
| C／C++ | 内部 Clang 解析 → `ParserClient` → 中間結果 | pixi は LLVM／Clang 11.1 系。C++ の定義、呼び出し、オーバーロード、マクロ、依存、診断、更新を試験 | C++20／23 全機能、modules、coroutines 等の対応証明はない。C の全規格も本変更の新規試験では網羅しない |
| Python | 外部索引器 → 作業 DB → Python 後処理 | 固定アーカイブ `v1_db25_p6`。試験ランナー Python 3.11 系と、旧索引器に渡す Python 3.8 系環境を分離 | Python 3.10 以降の構文一般や新しい型構文等の対応は未実装・未検証 |
| Java | 内部 Java 言語パッケージ | 実装は残っている | pixi の基準ビルドは Java OFF。既存言語だから自動的に検証済みとはしない |
| Custom | 外部コマンド、DB パス等の置換変数 | 既存の拡張入口 | 任意の外部索引器が共通契約を満たす保証はない |
| Rust | 専用アダプターなし | 本変更は必要な境界と受入条件を記述 | Rust の解析・Cargo 統合・UI 登録は未実装 |

根拠: [pixi.toml](../../pixi.toml)、[download_python_indexer.sh](../../script/download_python_indexer.sh)、[SourceGroupPythonEmpty.cpp](../../src/lib_python/project/SourceGroupPythonEmpty.cpp)、[SourceGroupSettingsWithCppStandard.cpp](../../src/lib/settings/source_group/component/cxx/SourceGroupSettingsWithCppStandard.cpp)。

現在の宣言能力を確認する再利用可能な入力として、[人工的な C++／Python 対象](../contracts/toy-problems.md) を追加する。独立した期待値に加え、無変更・削除・編集後の更新と全体更新、およびリファクタリング前後の保存観測を比較する。新しい解析器へ同じ入力を渡すことはできるが、旧版が理解しない構文の受入試験は別途追加する。

現行の C++ 標準選択肢には `c++2a`／`gnu++2a` と C++17 以前がある。選択肢に存在することは、その規格の全ての意味を記録できる保証ではない。Clang 自体も機能別の対応状況を公開しているため、更新は規格名だけでなく、機能と期待する索引結果で判定する。[Clang C++ status](https://clang.llvm.org/cxx_status.html)

## 提案するアダプターの契約

これは新 API が既に実装されたという記述ではない。Python 更新や Rust 実装に着手する前の設計条件である。[ADR-0004](../adr/0004-language-capabilities.md)

| 項目 | 宣言・入力に必要な内容 | 拒否または劣化表示する条件 |
| --- | --- | --- |
| 識別と版 | adapter ID、エンジン版、プロトコル版、対応 DB／観測版 | 不明なプロトコル版、対応外保存版 |
| 対応する言語 | language、対象バージョン／edition、対象機能 | 未対応の構文を黙って完全扱いしない |
| ビルド文脈 | include/import 探索、マクロ、target、sysroot、依存、環境 | 必要な設定が欠け、名前解決が成立しない |
| 記号同一性 | 修飾名、シグネチャ、パッケージ／crate／構成の区別 | 異なる対象が同じキーに衝突する |
| 関係能力 | 定義、呼び出し、使用、所属、型、継承／実装、依存 | 表現できない意味を別関係へ無条件に写さない |
| 確信度 | resolved、ambiguous、unresolved、診断、complete | 不完全な結果を空の成功として報告しない |
| 位置 | 文字コード、列の単位、起点、終端、生成コードの由来 | 元ソースへ写せない位置を通常位置と偽らない |
| 更新能力 | partial clearing、shallow、依存集合、取消、再試行 | 更新戦略の要求を満たせない場合は明示した全体更新等へ切替 |
| 実行条件 | コマンド、引数列、cwd、環境、タイムアウト、終了状態 | 子プロセス失敗、版交渉失敗、出力欠損 |

同じ「呼び出しをたどる」という操作を提供するために、全言語へ同一の構文分類を押し付ける必要はない。共通の最小能力と、言語固有の追加能力を別に定義する。

## Python を更新する作業

1. 旧索引器を再現できる基準環境を残し、候補となる解析エンジンを別環境で固定する。
2. 既存の対応構文では、名前、参照先、位置、状態、曖昧性の差分を比較する。診断文言の比較方針は事前に定める。
3. 新構文を機能単位で追加する。例: pattern matching、例外グループ、型パラメーター、型エイリアス。構文を読めるだけでなく、参照と所属の期待値を作る。
4. import の探索、仮想環境、namespace package、相対 import、複数の同名モジュールを検査する。
5. 浅い解析・完全解析・未解決参照の後処理・部分消去の能力を宣言し直す。

Python の `ast` は版ごとに構造が変わり得る。`ast.parse(feature_version=...)` は指定版の文法に近付ける手段であり、完全な名前解決や型推論を供給するものではない。AST の位置は UTF-8 バイトオフセットを使うため、位置の変換規則も固定する。[Python 3.14 ast](https://docs.python.org/3.14/library/ast.html)

## C++ の解析器を更新する作業

1. ビルド用コンパイラーの更新と、Clang 解析ライブラリーの更新を別の変更として検証する。
2. `CxxAstVisitor`、型解決、ソース位置、プリプロセッサー、診断の Clang API 依存をアダプターの内側へ集める。
3. compilation database の cwd、引数、マクロ、include、target、sysroot を入力の一部として比較する。
4. 共通の対応機能では旧版との比較を行い、新機能では正しい期待値との比較を行う。
5. modules、concepts、coroutines、template の変更は別の能力として試験する。成功した個別機能を「C++20 全対応」に広げない。

現在は Clang の C++ API を使う。公式資料は LibClang の安定した高水準 C インターフェースと、AST に深くアクセスする LibTooling を区別している。安定性だけを理由に切り替えると抽出できる意味を失う可能性があるため、必要な情報を保てるかを比較して選ぶ。[Clang Tooling](https://clang.llvm.org/docs/Tooling.html)

## Rust を追加する作業

アプリケーションの内部処理を Rust へ移すことと、Rust のソースを解析対象にすることは区別する。[ADR-0006](../adr/0006-portable-refresh-core.md) の値処理コアは、識別子集合による更新計画やコマンド変数展開を、Qt・Boost・SQLite から独立した検証単位にする。これは内部処理の移植に使える境界であり、以下の言語解析の責務を実装したものではない。

Rust ではソースファイルだけでなく、crate、edition、features、cfg、target、依存、build script や procedural macro の生成物が解析文脈に関わる。`cargo metadata --format-version 1` はワークスペースと依存の入口になるが、それだけで全ての意味解析結果が得られるわけではない。[Cargo metadata](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html)

候補として rust-analyzer の意味モデルを利用する案がある。公式設計では、ソースと crate graph を入力にし、意味モデルを生成する。Sourcetrail への統合方式（固定版のライブラリー、外部プロセス、LSP 等）は未決定であり、ここでは採用済みとはしない。[rust-analyzer architecture](https://rust-analyzer.github.io/book/contributing/architecture.html)

| Rust 固有事項 | 決める必要がある写像・観測 |
| --- | --- |
| module、crate、再エクスポート | 名前の同一性と公開名、依存元の区別 |
| trait、impl、associated item | 型／実装関係。クラス継承とは分けて意味を定義 |
| generic、monomorphization | 宣言と具体化をどの粒度で記録するか |
| macro_rules!、procedural macro | 展開後の記号と元ソース位置、生成物の由来 |
| cfg／features／target | 同一ファイルの別構成をどう区別するか |
| async／closure | 合成された対象と利用者のソースの対応 |
| 未解決・不完全なコード | 診断、部分結果、確信度、再試行 |

最初の受入範囲は、小さな Cargo workspace で定義・参照・呼び出し・ファイル依存・ソース位置・診断を確認し、rename／削除／再更新で古い記号が残らないことまでとする。高度なマクロや全 target を初回の合格へ暗黙に含めない。

## 新しい対象を組み込む際の変更箇所

| 領域 | 現在の具体的な入口 | 設計上の注意 |
| --- | --- | --- |
| ビルド | [CMakeLists.txt](../../CMakeLists.txt), `language_packages.h` の生成 | ツールのビルドと解析エンジンの配布を区別 |
| 設定の型と保存 | [LanguageType.cpp](../../src/lib/settings/LanguageType.cpp), [SourceGroupType.cpp](../../src/lib/settings/source_group/SourceGroupType.cpp), [ProjectSettings.cpp](../../src/lib/settings/ProjectSettings.cpp) | 永続化される文字列・移行を確認 |
| Source Group の生成 | [SourceGroupFactory.cpp](../../src/lib/project/SourceGroupFactory.cpp), 各 `SourceGroupFactoryModule*` | 対象列挙、除外、依存、部分消去を規定 |
| 実行側の登録 | [src/app/main.cpp](../../src/app/main.cpp), [src/indexer/main.cpp](../../src/indexer/main.cpp) | GUI 側だけ登録してもワーカーは動かない |
| 内部コマンド／IPC | [IndexerCommandType.h](../../src/lib/data/indexer/IndexerCommandType.h), [SharedIndexerCommand.cpp](../../src/lib/data/indexer/interprocess/shared_types/SharedIndexerCommand.cpp) | 列挙追加だけでは共有メモリー変換を満たさない |
| 外部実行 | [IndexerCommandCustom.cpp](../../src/lib/data/indexer/IndexerCommandCustom.cpp), [TaskExecuteCustomCommands.cpp](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp) | DB 版、並列書き込み、失敗、後処理を契約化 |
| 共通表現 | [ParserClient.h](../../src/lib/data/parser/ParserClient.h), [NodeKind.h](../../src/lib/data/NodeKind.h), [Edge.h](../../src/lib/data/graph/Edge.h) | 足りない意味は ADR と版変更を伴って追加 |
| 設定 UI・表示 | [QtProjectWizard.cpp](../../src/lib_gui/qt/project_wizard/QtProjectWizard.cpp), [NodeType.cpp](../../src/lib/data/NodeType.cpp) | 設定入力・フィルター・アイコン・探索表示を確認 |
| 検証 | [tests/python](../../tests/python/), [src/test](../../src/test/), [契約](../contracts/) | 対応能力の宣言と実行する例を一対一で追跡 |

新言語を `Custom` コマンドとして試作することはできるが、その時点で専用設定や全探索機能まで同等と宣言しない。

## 参照資料の扱い

上記の公式資料は 2026-10-30 に確認した設計根拠である。将来実装で採用する具体的なエンジン版は、選定時に固定し、対応表・ライセンス・配布条件・テスト結果を更新する。「最新」という変動する語を互換性契約の版指定として使わない。
