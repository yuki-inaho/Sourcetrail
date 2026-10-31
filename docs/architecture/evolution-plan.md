# 改善順序・調査範囲・未解決事項

この一覧は、索引化の概念を保ちながら内部構成と言語対応を改善するための作業地図である。更新日: 2026-10-31（Asia/Tokyo）。未検証事項を「既知の不具合」と決め付けず、実装から確認した性質と、追加実験が必要な懸念を区別する。

## 今回の到達点と、その先

| 段階 | 目的 | 成果／次の受入条件 |
| --- | --- | --- |
| 0: 基準の固定 | 既存挙動を再現する | pixi の依存固定、C++／Python の実アプリ試験、比較の観測範囲を記録 |
| 1: 意味と責務の分離 | 整理の単位を小さくする | `RefreshPlan` の抽出に続き、集合計画とコマンド変数展開を標準ライブラリーだけの `src/lib_core` へ分離。既存型・I/O はアダプターに残し、人工対象で実索引の観測を比較する |
| 2: アダプターの境界 | 解析エンジンを更新可能にする | 外部実行結果に加え、旧Python位置検査と新版アダプターの版・出力検査を接続。一般Customと取消・期限は残る |
| 3: 既存言語の更新 | 既存能力の保持と新能力の追加 | Python 3.14とClang 18の別アダプター、共通範囲比較と新機能の人工期待を実装 |
| 4: Rust の導入 | 共通の探索操作を新言語へ広げる | Cargo＋rust-analyzerの専用アダプター、記号写像・更新・診断・位置の人工対象を実装 |
| 5: 公開・問い合わせの整理 | 操作全体と障害耐性を保つ | DB 公開、キャッシュ、検索・経路・UI、ブックマークを独立した契約単位にする |

段階2は旧Python出力と新版アダプターの版・位置・グラフ検査まで進めた。段階3と4は[新版解析器](modern-indexers.md)に記載する機能単位で実装した。規格全体や任意構成への対応、一般のCustom出力、段階5の全課題を完了したとはしない。

段階 1 の具体的な境界は [ADR-0006](../adr/0006-portable-refresh-core.md)、変更前後に使用する入力と期待は [トイプロブレム](../contracts/toy-problems.md) を参照する。標準ライブラリーだけのコアを別環境からコンパイルできることと、解析エンジン・GUI・配布の移植が終わったことは別である。

## 調査範囲の一覧

「ソース確認」は実装の読解であり、新しい網羅試験や形式的証明ではない。

| 領域 | 根拠の入口 | 今回の扱い | 次に必要な観測 |
| --- | --- | --- | --- |
| プロジェクト設定・Source Group | [ProjectSettings.cpp](../../src/lib/settings/ProjectSettings.cpp), [SourceGroup.cpp](../../src/lib/project/SourceGroup.cpp) | ソース確認、設定・列挙境界を記述 | 保存／再読込／移動／除外／重複 |
| 更新計画 | [RefreshPlanner.h](../../src/lib_core/RefreshPlanner.h), [RefreshPlan.cpp](../../src/lib/project/RefreshPlan.cpp) | 値処理と依存問い合わせアダプターを分離、単独試験・契約・有限モデル | 入力分類と同一依存スナップショットの保証は別単位 |
| 外部コマンド構築 | [IndexerCommandTemplate.h](../../src/lib_core/IndexerCommandTemplate.h), [IndexerCommandCustom.cpp](../../src/lib/data/indexer/IndexerCommandCustom.cpp) | 変数展開を分離、引数境界・展開順・遅延 DB 切り替えを保持 | エンジン版・出力能力の交渉 |
| 外部実行結果 | [ExternalIndexerOutcome.h](../../src/lib_core/ExternalIndexerOutcome.h), [実行結果の契約](../contracts/external-indexing.md) | 起動・非ゼロ終了の分類、実行単位の集約、失敗候補の破棄、CLI終了を接続 | タイムアウト・取消・子孫回収・出力の意味検査 |
| 更新時刻・ファイル内容 | [RefreshInfoGenerator.cpp](../../src/lib/project/RefreshInfoGenerator.cpp) | 内容比較、空内容・保存欠落・読込失敗を区別。同時刻・逆行時刻を試験 | 入力群の原子的な取得と編集中の競合 |
| C++ 解析 | [lib_cxx](../../src/lib_cxx/), [新版アダプター](../../script/indexers/cpp_indexer.py) | 既存エンジンを維持しClang 18の定義・参照・呼出、CDB、modulesを機能別に検証 | 規格全体と任意のビルド構成 |
| Python 解析 | [lib_python](../../src/lib_python/), [新版アダプター](../../script/indexers/python_indexer.py) | 旧版UTF-8位置変換とPython 3.14の静的スコープ解析を実装 | 動的属性・一般型推論・実行時import |
| Java 解析 | [lib_java](../../src/lib_java/) | 経路のみ確認 | Java を有効にしたビルド・適合試験 |
| Rust | [専用ソース索引器](../../script/indexers/rust_indexer.py) | Cargo＋rust-analyzerでworkspace、trait/impl、呼出、診断、位置を実装・検証 | proc-macro・build.rs依存構成、任意target |
| 中間表現・統合 | [Storage.cpp](../../src/lib/data/storage/Storage.cpp), [IntermediateStorage.cpp](../../src/lib/data/storage/IntermediateStorage.cpp) | ID 対応と付加情報を確認 | 注入順の変更、欠損・例外 |
| 永続化・スキーマ | [SqliteIndexStorage.cpp](../../src/lib/data/storage/sqlite/SqliteIndexStorage.cpp) | 全テーブルの意味を整理 | スキーマ移行、破損入力 |
| ファイル削除時の所属関係 | [StorageCleanupContractTestSuite.cpp](../../src/test/StorageCleanupContractTestSuite.cpp), [トイプロブレム](../contracts/toy-problems.md) | 既存の所属辺欠落を検出し、両端が残る所属辺を保持する限定修正 | 他の関係種類・巨大入力の一般保証は含めない |
| 公開・取消・復旧 | [Project.cpp](../../src/lib/project/Project.cpp), [TaskFinishParsing.cpp](../../src/lib/data/TaskFinishParsing.cpp) | 外部実行失敗が判明した候補を破棄。採用中の非原子的な公開箇所は残る | 公開中の障害注入と復旧手順、取消 |
| ワーカー・IPC | [interprocess](../../src/lib/data/indexer/interprocess/) | 拡張時の経路を確認 | 中断、ワーカー終了、版不一致 |
| 検索・グラフ・コード | [StorageAccess.h](../../src/lib/data/storage/StorageAccess.h) | 問い合わせ表を作成 | 意味単位の問い合わせ適合試験 |
| キャッシュ | [StorageCache.cpp](../../src/lib/data/storage/StorageCache.cpp) | 再構築と診断中の内容選択を確認 | 更新前後・取消後の古い結果の排除 |
| ブックマーク | [SqliteBookmarkStorage.cpp](../../src/lib/data/storage/sqlite/SqliteBookmarkStorage.cpp) | 索引と独立した移行対象を確認 | 名前規約変更、復元、再索引化 |
| GUI・IDE 連携 | [lib_gui](../../src/lib_gui/), [NetworkProtocolHelper.cpp](../../src/lib/component/controller/helper/NetworkProtocolHelper.cpp) | 入口と未検証範囲を整理 | 実 GUI、フォーカス、履歴、外部エディター往復 |
| 配布・OS・性能 | [pixi.toml](../../pixi.toml), [CMakeLists.txt](../../CMakeLists.txt) | Linux 基準に限定 | 他 OS、巨大入力、メモリー・所要時間 |

## 未解決事項の一覧

優先度は、今後の変更を安全に進めるための順序であり、直ちに発生する障害の頻度を測定した値ではない。`高` は関連部分を変更する前の確認、`中` は能力拡張時の受入条件、`継続` は反復して観測するものを示す。

| ID | 論点 | 優先度 | 状態 | 詳細 |
| --- | --- | --- | --- | --- |
| GAP-001 | DB 公開の障害耐性 | 高 | 実装上の制約を確認、改善は未実装 | 下記 |
| GAP-002 | 更新時刻に依存する変更検出 | 高 | 内容観測と失敗分類を実装・検証。原子的取得は別課題 | 下記 |
| GAP-003 | 列位置と文字コードの規約 | 高 | 旧Python変換と新版3言語の保存UTF-8規約を実装・検証 | 下記 |
| GAP-004 | Source Group の包含・所属判定と部分消去 | 高 | 本変更で修正、回帰試験を追加 | 下記 |
| GAP-005 | 外部索引器の失敗と終了状態 | 高 | 起動・非ゼロ終了、旧Python／新版出力検査を実装。一般Custom・タイムアウト・取消は残る | 下記 |
| GAP-006 | Python／C++ の新構文 | 中 | Python3.14／Clang18の機能別アダプターを実装・検証 | 下記 |
| GAP-007 | Rust アダプター | 中 | Cargo＋rust-analyzer、定義・参照・呼出・更新を実装・検証 | 下記 |
| GAP-008 | 検索・UI の観測契約 | 高 | DB 比較では範囲外の部分あり | 下記 |
| GAP-009 | 同一性・スキーマ・移行 | 高 | 多言語・多構成での仕様追加が必要 | 下記 |
| GAP-010 | 並行処理とスナップショット | 高 | 有限更新モデルの対象外 | 下記 |
| GAP-011 | OS・配布の互換性 | 中 | Linux 以外は今回の基準外 | 下記 |
| GAP-012 | 性能・規模 | 継続 | 非機能の基準値未整備 | 下記 |

### GAP-001: DB 公開の障害耐性

`Project::swapToTempStorageFile` は旧 DB を削除してから一時 DB を rename する。トランザクションやモデル上の一遷移だけを根拠に、障害時の旧／新版保存を保証できない。

次の作業は、同一ファイルシステム上の置き換え方針、バックアップ・復旧、起動時の一時 DB 検出を設計し、削除直後・rename 前後・ファイル使用中の障害を注入すること。受入条件は、索引を復元でき、ブックマークを損なわず、採用中の版が判定可能なことである。[Project.cpp](../../src/lib/project/Project.cpp)

### GAP-002: 更新時刻に依存する変更検出

[SourceChange](../../src/lib_core/SourceChange.h)を再実装し、取得できた保存内容と現在内容を比較する。mtimeが同一・過去でも内容差を検出し、内容不変のtouchでは再解析しない。空内容、保存行の欠落、NULL、SQL失敗、ファイル読込失敗を区別する。[ADR-0008](../adr/0008-content-based-input-observations.md)

[人工対象](../../tests/input_observation/test_input_observation.py)で定義・保存内容・再実行数を確認し、変更・空化後をclean再構築と比較する。保存内容を持たない非索引依存にはmtimeの弱い互換判定が残る。入力群全体の原子的取得は未保証であり、今回の内容観測から推論しない。

### GAP-003: 列位置と文字コードの規約

[LOCATION-001](../contracts/input-observations.md)に従い、保存位置を1始まり・UTF-8バイト・終端込みとする。旧PythonのUnicode文字位置は全ワーカー後にDB／ソースごとに一度変換する。BOM、CRLF、最終改行、ゼロ幅境界、不正UTF-8・範囲外を扱い、異常出力は採用しない。[ADR-0009](../adr/0009-canonical-python-source-positions.md)

新版Python/C++/Rustはエンジンの位置をこの保存規約へ写し、実トークンを独立に検査する。旧Python DBは全体再索引化が必要で、自動判別移行はしない。表示層全体・全Unicode規格・あらゆる生成マクロの位置保証とは区別する。

### GAP-004: Source Group の包含判定

変更前の `filterToContainedSourceFilePath(X)` は名前と異なり、グループの全ソース集合から `X` を除いた集合を返していた。`containsSourceFilePath(x)` はその結果が空でないかを返していたため、ソース集合が `{x}` なら false、`{x, y}` で無関係な `z` を渡せば true となり、通常の包含判定と一致しなかった。

本変更では `SOURCE-GROUP-001` として、`containsSourceFilePath` を集合の包含判定へ修正する。補集合を返す操作は `getSourceFilePathsExcept` と明示し、不完全再試行の呼び出しを移す。旧 API は転送用の別名として残す。単一ファイル・複数ファイル・グループ外ファイル等の回帰試験を追加した。

加えて、`Project::buildIndex` の部分消去から全体更新への切り替えには、現在のソース集合への包含ではなく、設定上の所属を返す `filterToContainedFilePaths` を使う。削除済みパスは現在の集合にないが、設定上はグループに所属し得る。先に調べた部分消去不可グループに該当しない場合も、後続のグループを調べる。変更前の無条件の `break` は、後続グループの該当を見落としていた。shallow 指定と GUI の確認／取消は保持する。[Project.cpp](../../src/lib/project/Project.cpp)

回帰の観測点は、削除済みパス、除外条件、ディレクトリ名の接頭辞が似た別パス、明示した単一ファイルを扱う C++ 試験と、二つの Python Source Group のうち後のグループから一ファイルだけを削除する E2E である。後者は生存ファイルの編集に依存せず全体更新へ進み、残る二ファイルを再索引化することを検査する。[SourceGroupContractTestSuite.cpp](../../src/test/SourceGroupContractTestSuite.cpp)、[test_e2e.py](../../tests/python/test_e2e.py)

これらは更新計画の等価な抽出とは**別の、意図した振る舞い修正**である。既存の誤った結果と同一であるとは主張しない。[SourceGroup.cpp](../../src/lib/project/SourceGroup.cpp)

### GAP-005: 外部索引器の失敗と終了状態

変更前は非ゼロ終了を記録した後も索引済み数へ加算し、終了処理に実行失敗が渡らなかった。`EXECUTION-001` では、プロセスヘルパーの実行エラーと非ゼロ終了を成功数へ含めず、一回の実行で失敗を保持する。失敗候補の破棄・更新段階の解除・終了通知を完了し、CLIは非ゼロ終了を返す。実行失敗が判明した候補を採用しない範囲の変更である。[ADR-0007](../adr/0007-external-indexer-outcomes.md)、[外部実行の契約](../contracts/external-indexing.md)

`GAP-005` 全体は未完了である。一般Customではstderr付きの終了コード0と書き込みなしの終了コード0をプロセス成功とする既存の分類が残る。CLIの終了コードだけで意味的に完全な索引があるとは判断しない。一般Custom全体に破損DB、空出力、未対応保存版・エンジン版の拒否を広げるには、能力と出力の契約を接続する必要がある。

旧Pythonの不整合位置と新版アダプターの版・グラフ出力は今回拒否する。任意Customコマンド全体にはまだ適用しない。[入力観測](../contracts/input-observations.md)、[新版解析器](modern-indexers.md)。

タイムアウトと取消も別途確認する。現行の [executeProcess](../../src/lib_gui/utility/utilityApp.cpp) は `ios.run()` によるパイプ読込を行ってからタイムアウト付き待機へ進む。この呼び出し順はソースで確認したが、特定のハングを再現したという証跡ではない。タイマー・子プロセス終了・パイプ読込・子孫回収を含む実験が必要になる。

次の受入条件は、取消・期限超過・破損出力・未対応版をそれぞれ別の人工対象で再現し、結果状態、候補の処分、既存索引の保持、再試行可能な終了を確認することである。構文診断の有無とプロセス失敗を一つのフラグにまとめない。[TaskExecuteCustomCommands.cpp](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp)

### GAP-006: Python／C++ の新構文

Python 3.14のastとClang 18.1.8のC索引APIを独立環境へ固定した。新構文を受け入れ、定義・参照・呼出・診断・保存位置を共通グラフへ写す。旧エンジンも比較基準として維持する。[ADR-0011](../adr/0011-modern-language-adapters.md)、[ADR-0012](../adr/0012-modern-cpp-indexer.md)

共通能力は手書き期待と旧版の観測、新構文は機能別の人工対象で検証する。Pythonの動的推論やC++規格全体の適合を宣言しない。対応と制約は[能力表](../contracts/language-profiles.json)と[利用手順](modern-indexers.md)へ固定する。

### GAP-007: Rust アダプター

Cargo workspaceとrust-analyzerの意味問い合わせを利用する専用ソース索引器を実装した。定義、参照、呼出、module依存、trait/impl、マクロ呼出元、診断、UTF-8位置を保存し、変更・削除後の再解析をclean結果と比較する。[ADR-0013](../adr/0013-rust-source-indexer.md)

crate／構成の同一性とfeatures/targetを明示する。proc-macroやbuild.rs依存構成は今回の対応範囲外として拒否する。更新はネイティブModernグループの全体再構築を使う。既存のRust更新ポリシー参照移植とは別の成果であり、全Rust機能・全target・実GUI操作の保証へ広げない。

### GAP-008: 検索・UI の観測契約

SQLite の意味比較だけでは、候補順位、フィルター、経路の深さ・方向、コード表示、履歴、外部エディター往復を保証できない。

次の作業は `StorageAccess` の問い合わせを意味上のキーで比較する試験を作り、その後に代表的な GUI 操作を追加すること。受入条件は、保存グラフの一致と問い合わせ結果の一致を別々に判定できることである。[storage-and-query.md](storage-and-query.md)

### GAP-009: 同一性・スキーマ・移行

保存名の規約、外部索引器の整数列挙、DB 版、ブックマークの保存名には互換性の結合がある。多言語・複数構成の区別を後から曖昧に追加しない。

次の作業は、言語・パッケージ・構成・修飾名・シグネチャの同一性規約を ADR で固定すること。受入条件は、同名衝突を判定でき、移行／再索引化／ブックマーク復元の扱いが決まり、不明な版を明示的に拒否することである。[domain-model.md](domain-model.md)、[storage-and-query.md](storage-and-query.md)

### GAP-010: 並行処理とスナップショット

更新計画モデルは固定された依存集合を仮定する。外部実行結果のモデルではコマンドの開始・結果確定の順序と失敗保持を扱うが、内部ワーカーの停止、キュー完了、取消、DB注入順、途中の入力変更、キャッシュの切り替えは検証していない。外部実行状態への同期追加を、索引処理全体の並行安全性の証明へ広げない。

次の作業は、実行順序を観測できるイベント記録と、停止・再試行の状態機械を定義すること。受入条件は、欠落・二重注入・古いキャッシュを検知し、モデルの前提を実装側のどの箇所が保証するか追跡できることである。[Project.cpp](../../src/lib/project/Project.cpp)、[interprocess](../../src/lib/data/indexer/interprocess/)

### GAP-011: OS・配布の互換性

pixi の対象は `linux-64`。パス、ファイル名の大小文字、シンボリックリンク、プロセス引数、共有メモリー、DB rename は OS 差の影響を受ける。

次の作業は対象 OS を決めて依存と配布方法を固定し、同じ能力の適合試験を走らせること。Linux 上の成功やアーカイブのハッシュ確認だけで Windows／macOS の実行互換性を宣言しない。[pixi-development.md](../pixi-development.md)

### GAP-012: 性能・規模

意味を保つ変更でも巨大なプロジェクトで実用性を損なう可能性がある。今回の小さな例の成功は性能保証ではない。

次の作業は、公開可能な代表入力を固定し、全体／差分索引化、検索遅延、最大メモリー、DB サイズを記録すること。受入条件は、環境・入力版・ばらつきを含む基準値と許容差があり、意味の比較結果と併記されることである。

## 変更単位の終了条件

1. 変更が守る契約と、変更する仕様を識別子で列挙する。
2. 変更前の観測または独立した期待を保存する。
3. 該当する実行試験・モデル・差分比較を行い、コマンドと結果をレポートへ記録する。
4. 差が出た場合は、回帰・意図した改善・比較条件の不一致に分け、根拠を示す。
5. ADR、対応能力、未解決事項、次のレビュー入力を更新する。
6. 未実行の確認を成功扱いせず、残る前提をレポートに残す。

この終了条件は、各変更に明確な範囲を与えるためのものであり、文書一式を作れば全ての GAP が閉じるという意味ではない。
