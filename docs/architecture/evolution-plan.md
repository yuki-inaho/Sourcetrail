# 改善順序・調査範囲・未解決事項

この一覧は、索引化の概念を保ちながら内部構成と言語対応を改善するための作業地図である。調査日: 2026-10-30。未検証事項を「既知の不具合」と決め付けず、実装から確認した性質と、追加実験が必要な懸念を区別する。

## 今回の到達点と、その先

| 段階 | 目的 | 成果／次の受入条件 |
| --- | --- | --- |
| 0: 基準の固定 | 既存挙動を再現する | pixi の依存固定、C++／Python の実アプリ試験、比較の観測範囲を記録 |
| 1: 意味と責務の分離 | 整理の単位を小さくする | `RefreshPlan` の抽出に続き、集合計画とコマンド変数展開を標準ライブラリーだけの `src/lib_core` へ分離。既存型・I/O はアダプターに残し、人工対象で実索引の観測を比較する |
| 2: アダプターの境界 | 解析エンジンを更新可能にする | 版・構文・能力・位置規約・実行失敗の契約を、実装と適合試験へ接続 |
| 3: 既存言語の更新 | 既存能力の保持と新能力の追加 | Python と C++ を別変更で更新し、共通範囲比較と新機能の期待値を両方通す |
| 4: Rust の導入 | 共通の探索操作を新言語へ広げる | Cargo 文脈、記号の写像、更新・診断・位置の最小能力を実装し適合試験を通す |
| 5: 公開・問い合わせの整理 | 操作全体と障害耐性を保つ | DB 公開、キャッシュ、検索・経路・UI、ブックマークを独立した契約単位にする |

段階 2 以降の実装は、この文書があるだけでは完了しない。本変更の試験・形式モデルの成功から、新版 Python／C++ や Rust の対応完了を推論してはいけない。

段階 1 の具体的な境界は [ADR-0006](../adr/0006-portable-refresh-core.md)、変更前後に使用する入力と期待は [トイプロブレム](../contracts/toy-problems.md) を参照する。標準ライブラリーだけのコアを別環境からコンパイルできることと、解析エンジン・GUI・配布の移植が終わったことは別である。

## 調査範囲の一覧

「ソース確認」は実装の読解であり、新しい網羅試験や形式的証明ではない。

| 領域 | 根拠の入口 | 今回の扱い | 次に必要な観測 |
| --- | --- | --- | --- |
| プロジェクト設定・Source Group | [ProjectSettings.cpp](../../src/lib/settings/ProjectSettings.cpp), [SourceGroup.cpp](../../src/lib/project/SourceGroup.cpp) | ソース確認、設定・列挙境界を記述 | 保存／再読込／移動／除外／重複 |
| 更新計画 | [RefreshPlanner.h](../../src/lib_core/RefreshPlanner.h), [RefreshPlan.cpp](../../src/lib/project/RefreshPlan.cpp) | 値処理と依存問い合わせアダプターを分離、単独試験・契約・有限モデル | 入力分類と同一依存スナップショットの保証は別単位 |
| 外部コマンド構築 | [IndexerCommandTemplate.h](../../src/lib_core/IndexerCommandTemplate.h), [IndexerCommandCustom.cpp](../../src/lib/data/indexer/IndexerCommandCustom.cpp) | 変数展開を分離、引数境界・展開順・遅延 DB 切り替えを保持 | 実行失敗・取消・版交渉の再設計は別単位 |
| 更新時刻・ファイル内容 | [RefreshInfoGenerator.cpp](../../src/lib/project/RefreshInfoGenerator.cpp) | 条件を明記 | 同時刻・逆行時刻・削除・編集競合 |
| C++ 解析 | [lib_cxx](../../src/lib_cxx/) | 基準試験と拡張点整理 | 新規構文・異なるビルド構成 |
| Python 解析 | [lib_python](../../src/lib_python/), [外部処理](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp) | 基準試験、後処理・環境分離を記述 | 新版構文、import、曖昧性 |
| Java 解析 | [lib_java](../../src/lib_java/) | 経路のみ確認 | Java を有効にしたビルド・適合試験 |
| Rust | [言語拡張設計](language-compatibility.md) | 提案 | アダプター選定・実装・受入試験 |
| 中間表現・統合 | [Storage.cpp](../../src/lib/data/storage/Storage.cpp), [IntermediateStorage.cpp](../../src/lib/data/storage/IntermediateStorage.cpp) | ID 対応と付加情報を確認 | 注入順の変更、欠損・例外 |
| 永続化・スキーマ | [SqliteIndexStorage.cpp](../../src/lib/data/storage/sqlite/SqliteIndexStorage.cpp) | 全テーブルの意味を整理 | スキーマ移行、破損入力 |
| ファイル削除時の所属関係 | [StorageCleanupContractTestSuite.cpp](../../src/test/StorageCleanupContractTestSuite.cpp), [トイプロブレム](../contracts/toy-problems.md) | 既存の所属辺欠落を検出し、両端が残る所属辺を保持する限定修正 | 他の関係種類・巨大入力の一般保証は含めない |
| 公開・取消・復旧 | [Project.cpp](../../src/lib/project/Project.cpp), [TaskFinishParsing.cpp](../../src/lib/data/TaskFinishParsing.cpp) | 非原子的な公開箇所を記録 | 障害注入と復旧手順 |
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
| GAP-002 | 更新時刻に依存する変更検出 | 高 | 条件を確認、完全性は未保証 | 下記 |
| GAP-003 | 列位置と文字コードの規約 | 高 | 横断契約が未整備 | 下記 |
| GAP-004 | Source Group の包含・所属判定と部分消去 | 高 | 本変更で修正、回帰試験を追加 | 下記 |
| GAP-005 | 外部索引器の失敗と終了状態 | 高 | 結果の意味検査が必要 | 下記 |
| GAP-006 | Python／C++ の新構文 | 中 | 新しい対応能力は未実装 | 下記 |
| GAP-007 | Rust アダプター | 中 | 設計・実装待ち | 下記 |
| GAP-008 | 検索・UI の観測契約 | 高 | DB 比較では範囲外の部分あり | 下記 |
| GAP-009 | 同一性・スキーマ・移行 | 高 | 多言語・多構成での仕様追加が必要 | 下記 |
| GAP-010 | 並行処理とスナップショット | 高 | 有限更新モデルの対象外 | 下記 |
| GAP-011 | OS・配布の互換性 | 中 | Linux 以外は今回の基準外 | 下記 |
| GAP-012 | 性能・規模 | 継続 | 非機能の基準値未整備 | 下記 |

### GAP-001: DB 公開の障害耐性

`Project::swapToTempStorageFile` は旧 DB を削除してから一時 DB を rename する。トランザクションやモデル上の一遷移だけを根拠に、障害時の旧／新版保存を保証できない。

次の作業は、同一ファイルシステム上の置き換え方針、バックアップ・復旧、起動時の一時 DB 検出を設計し、削除直後・rename 前後・ファイル使用中の障害を注入すること。受入条件は、索引を復元でき、ブックマークを損なわず、採用中の版が判定可能なことである。[Project.cpp](../../src/lib/project/Project.cpp)

### GAP-002: 更新時刻に依存する変更検出

`didFileChange` は保存時刻より新しい mtime の時だけ内容比較を行う。同じ時刻・過去時刻で内容を置き換えた場合を一般に拾う仕様ではない。固定版の外部 Python 索引器は入力の mtime ではなく記録時の時刻を保存するため、コピーした試験データの古い mtime に数秒足すだけでは条件を満たさない。今回の Python E2E は元の mtime と直前の索引化後の現在時刻の両方より新しい時刻に設定する。入力条件の修正であり、この検出方式の制約は残る。[時刻の根拠と試験](indexing-lifecycle.md#純粋計画の外に残る判定)

次の作業は、期待する変更検出の契約を決め、ハッシュ等を使う必要とコストを評価すること。受入条件は、同時刻変更、時刻逆行、内容不変の touch、削除、入力読み込み中の変更を、期待する扱いに分類できることである。[RefreshInfoGenerator.cpp](../../src/lib/project/RefreshInfoGenerator.cpp)

### GAP-003: 列位置と文字コードの規約

1 始まり・終端込みとして使用される箇所がある一方、全アダプターと表示層の列単位は統一的に検証されていない。`ParseLocation::isValid` はファイル ID のみを確認する。

次の作業は、アダプター入力の座標規約と共通観測の座標規約を定め、Unicode・改行・マクロ由来の位置を試験すること。受入条件は、範囲内の位置が正しいトークンを示し、変換できない位置が明示的に扱われることである。[domain-model.md](domain-model.md)

### GAP-004: Source Group の包含判定

変更前の `filterToContainedSourceFilePath(X)` は名前と異なり、グループの全ソース集合から `X` を除いた集合を返していた。`containsSourceFilePath(x)` はその結果が空でないかを返していたため、ソース集合が `{x}` なら false、`{x, y}` で無関係な `z` を渡せば true となり、通常の包含判定と一致しなかった。

本変更では `SOURCE-GROUP-001` として、`containsSourceFilePath` を集合の包含判定へ修正する。補集合を返す操作は `getSourceFilePathsExcept` と明示し、不完全再試行の呼び出しを移す。旧 API は転送用の別名として残す。単一ファイル・複数ファイル・グループ外ファイル等の回帰試験を追加した。

加えて、`Project::buildIndex` の部分消去から全体更新への切り替えには、現在のソース集合への包含ではなく、設定上の所属を返す `filterToContainedFilePaths` を使う。削除済みパスは現在の集合にないが、設定上はグループに所属し得る。先に調べた部分消去不可グループに該当しない場合も、後続のグループを調べる。変更前の無条件の `break` は、後続グループの該当を見落としていた。shallow 指定と GUI の確認／取消は保持する。[Project.cpp](../../src/lib/project/Project.cpp)

回帰の観測点は、削除済みパス、除外条件、ディレクトリ名の接頭辞が似た別パス、明示した単一ファイルを扱う C++ 試験と、二つの Python Source Group のうち後のグループから一ファイルだけを削除する E2E である。後者は生存ファイルの編集に依存せず全体更新へ進み、残る二ファイルを再索引化することを検査する。[SourceGroupContractTestSuite.cpp](../../src/test/SourceGroupContractTestSuite.cpp)、[test_e2e.py](../../tests/python/test_e2e.py)

これらは更新計画の等価な抽出とは**別の、意図した振る舞い修正**である。既存の誤った結果と同一であるとは主張しない。[SourceGroup.cpp](../../src/lib/project/SourceGroup.cpp)

### GAP-005: 外部索引器の失敗と終了状態

外部コマンドの非ゼロ終了は記録されるが、現在の実行タスクではコマンド後の処理数も増える。CLI の終了だけを「意味のある完全な索引がある」と解釈できない。

次の作業は、実行失敗・構文診断・部分結果・取消・タイムアウトの状態を分離すること。受入条件は、起動不可、途中失敗、空出力、破損 DB、未対応版で、適切な結果状態と復旧可能な索引を残すことである。[TaskExecuteCustomCommands.cpp](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp)

### GAP-006: Python／C++ の新構文

現在の固定環境は、新しい構文を一般に保証しない。試験ランナー版と解析対象版を分け、構文・名前解決・位置・診断を能力単位で増やす。

受入条件は、共通の対応範囲で旧版との比較を通し、新能力について独立した期待を満たすこと。具体的な順序は [language-compatibility.md](language-compatibility.md) を参照する。

### GAP-007: Rust アダプター

専用実装は存在しない。Cargo 文脈と意味モデルの選択、trait／impl と共通関係の写像、マクロ位置を先に決める。

受入条件は、小さな workspace を対象に定義・参照・呼び出し・依存・診断・位置を記録し、検索と変更／削除後の更新まで一貫して動くこと。最初から全 Rust 機能への対応を宣言しない。[language-compatibility.md](language-compatibility.md)

`src/lib_core` の値処理は、Rust 等へ移す際の小さな検証単位を提供する。Rust で同じ計画を計算できることを確認しても、この GAP の Rust ソース索引化が完了したとはしない。[ADR-0006](../adr/0006-portable-refresh-core.md)

### GAP-008: 検索・UI の観測契約

SQLite の意味比較だけでは、候補順位、フィルター、経路の深さ・方向、コード表示、履歴、外部エディター往復を保証できない。

次の作業は `StorageAccess` の問い合わせを意味上のキーで比較する試験を作り、その後に代表的な GUI 操作を追加すること。受入条件は、保存グラフの一致と問い合わせ結果の一致を別々に判定できることである。[storage-and-query.md](storage-and-query.md)

### GAP-009: 同一性・スキーマ・移行

保存名の規約、外部索引器の整数列挙、DB 版、ブックマークの保存名には互換性の結合がある。多言語・複数構成の区別を後から曖昧に追加しない。

次の作業は、言語・パッケージ・構成・修飾名・シグネチャの同一性規約を ADR で固定すること。受入条件は、同名衝突を判定でき、移行／再索引化／ブックマーク復元の扱いが決まり、不明な版を明示的に拒否することである。[domain-model.md](domain-model.md)、[storage-and-query.md](storage-and-query.md)

### GAP-010: 並行処理とスナップショット

今回の更新モデルは固定された依存集合を仮定する。ワーカーの停止、キュー完了、取消、注入順、途中の入力変更、キャッシュの切り替えは検証していない。

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
