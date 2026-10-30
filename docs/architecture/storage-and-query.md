# 保存形式と問い合わせの内部仕様

## ファイルとバージョン

| ファイル | 用途 | 現行のバージョン情報 |
| --- | --- | --- |
| `.srctrlprj` | Source Group 等のプロジェクト設定 | 設定の読み込み・移行は `ProjectSettings` が担当 |
| `.srctrldb` | 採用した索引 | `meta.storage_version = 25` |
| `.srctrldb_tmp` | 索引作成中の一時 DB | 採用時に本索引へ置き換える |
| `.srctrlbm` | ブックマーク | `SqliteBookmarkStorage::s_storageVersion = 2` |

根拠: [ProjectSettings.cpp](../../src/lib/settings/ProjectSettings.cpp)、[SqliteIndexStorage.cpp](../../src/lib/data/storage/sqlite/SqliteIndexStorage.cpp)、[SqliteBookmarkStorage.cpp](../../src/lib/data/storage/sqlite/SqliteBookmarkStorage.cpp)。

索引 DB が作り直せても、利用者が付けたブックマークが自動的に作り直せるわけではない。記号の命名規約を変える際は、索引とブックマークを別の移行対象として扱う。

## 索引スキーマの全体

以下は `SqliteIndexStorage::setupTables` と `SqliteStorage::setupMetaTable` の意味上の一覧である。型・制約の正本は実装であり、新スキーマを導入する場合はこの表と比較器を同時に更新する。

| テーブル | 主な内容 | 参照関係・意味 |
| --- | --- | --- |
| `meta` | key / value | 保存版、設定文字列、時刻等 |
| `element` | 要素 ID | node、edge、local symbol、error 等の共通 ID 空間 |
| `node` | type、serialized_name | 記号／ファイル／階層ノード。ID は `element` を参照 |
| `symbol` | definition_kind | `node` の定義状態 |
| `edge` | type、source_node_id、target_node_id | 両端の `node` と要素 ID を参照 |
| `file` | path、language、modification_time、indexed、complete、line_count | `node` のファイル情報。時刻の意味は生産元による |
| `filecontent` | content | `file` の索引時内容。全ファイルに必ず存在するわけではない |
| `local_symbol` | name | 局所記号の記録。名前にスコープ等の識別情報が含まれる場合がある |
| `source_location` | file_node_id、開始・終了行列、type | ファイル上の領域 |
| `occurrence` | element_id、source_location_id | 要素がどの位置に現れるか。二列が主キー |
| `component_access` | node_id、type | public/private 等のアクセス種別 |
| `element_component` | element_id、type、data | 曖昧性等の付加情報 |
| `error` | message、fatal、indexed、translation_unit | 診断。位置は `occurrence` からたどる |

`element_id_to_clear` は消去処理に用いる作業用テーブルであり、ドメインの独立した概念ではない。

`modification_time` を全経路で入力ファイルの mtime と同一視しない。内蔵 `SqliteIndexStorage::addFile` は指定が空なら入力の最終更新時刻を補うが、固定版の外部 Python 索引器が使用する SourcetrailDB は記録時の時刻を渡す。更新判定が要求する大小関係と試験での扱いは、[更新ライフサイクル](indexing-lifecycle.md#純粋計画の外に残る判定) にまとめる。

`SqliteStorage` は通常 `PRAGMA foreign_keys=ON` を設定する。多数の子関係には削除時の cascade がある。一方、名前・関係の意味上の重複排除は SQL 制約だけで完結せず、`IntermediateStorage` と `SqliteIndexStorage` の索引・集合処理にも依存する。外部索引器が DB を書けることは、意味上の整合性まで満たしたことを意味しない。

## 注入・消去・キャッシュ

`Storage::inject` は、独立した中間結果を保存先へ統合する際に ID を付け直す。対応表を用いて関係の両端、位置のファイル、出現、アクセス、付加情報を再接続する。`PersistentStorage` の注入はトランザクションで囲まれるが、プロジェクト全体の更新が一つのトランザクションであるわけではない。[Storage.cpp](../../src/lib/data/storage/Storage.cpp)

`clearFileElements` は指定ファイルの位置に属する要素を整理した後、ファイルノードを削除する。共有する記号・関係を残す必要があり、ファイル数だけを比較しても更新の正しさは検査できない。[PersistentStorage.cpp](../../src/lib/data/storage/PersistentStorage.cpp)、[StorageTestSuite.cpp](../../src/test/StorageTestSuite.cpp)

`SqliteIndexStorage::setMode` は READ／WRITE／CLEAR に応じて DB 索引を切り替え、書き込み補助の一時索引をクリアする。`PersistentStorage::buildCaches` はファイルパス、記号検索、所属順序、階層等を再構築する。`StorageCache` は一部のグラフ・統計・診断をさらにキャッシュする。DB が同じでも、更新後に古いキャッシュが残れば利用者から見た意味は異なる。

## 問い合わせ契約の候補と現行の観測点

| 観測単位 | 主 API | 確認すべき結果 | 既存の手掛かり |
| --- | --- | --- | --- |
| 名前→対象、対象→名前 | `getNodeIdForNameHierarchy`, `getNameHierarchyForNodeId` | 階層・シグネチャを保った対応 | [StorageTestSuite.cpp](../../src/test/StorageTestSuite.cpp) |
| 自動補完 | `getAutocompletionMatches` | 候補、型フィルター、コマンド混入条件、順位、上限 | [SearchIndexTestSuite.cpp](../../src/test/SearchIndexTestSuite.cpp) |
| 全文検索 | `getFullTextSearchLocations` | 大小文字設定、文字コード、位置、ファイル内容 | `PersistentStorage` の全文検索索引 |
| 選択対象のグラフ | `getGraphForActiveTokenIds` | 関係、親の補完、展開状態、曖昧性 | [GraphController.cpp](../../src/lib/component/controller/GraphController.cpp) |
| 関係経路 / trail | `getGraphForTrail` | 始点・終点・方向・深さ・型マスク・非索引対象 | [PersistentStorage.cpp](../../src/lib/data/storage/PersistentStorage.cpp) |
| 参照位置 | `getSourceLocationsForTokenIds` | 同じ対象の全出現、位置種別、ファイル状態 | [CodeController.cpp](../../src/lib/component/controller/CodeController.cpp) |
| 位置→対象 | `getNodeIdsForLocationIds` | 辺なら参照先へ、暗黙定義の優先規則 | `PersistentStorage::getNodeIdsForLocationIds` |
| 診断 | `getErrorsLimited`, `getErrorsForFileLimited` | fatal、indexed、制限、対象ファイル、位置 | [StorageAccess.h](../../src/lib/data/storage/StorageAccess.h) |
| ブックマーク | `getAllNodeBookmarks`, `getAllEdgeBookmarks` 等 | 再索引化後も意味上の対象に解決できるか | [SqliteBookmarkStorageTestSuite.cpp](../../src/test/SqliteBookmarkStorageTestSuite.cpp) |

この一覧は全 API を新しい自動試験で網羅したという意味ではない。既存の下位試験があっても、UI の操作から同じ結果が見えることは別の検証である。将来の問い合わせ境界の分離は、この表を契約の追加順序として用いる。

### 自動補完

現在は記号・ファイル・コマンドの候補を組み合わせ、スコアを再計算し、上限 1000 件で返す。型フィルターと検索文字列が入力の一部である。順序を無条件にソートして比較すると、順位の回帰を隠す。[PersistentStorage.cpp](../../src/lib/data/storage/PersistentStorage.cpp) の `getAutocompletionMatches`

### グラフと経路

グラフ問い合わせは保存された辺の単純な全件取得ではない。親ノード補完、選択状態、ノード型・辺型マスク、方向、深さ、非索引対象の許可等を反映する。経路の深さ `0` は無制限として扱う。保存グラフの比較と、問い合わせ結果の比較を分ける。

### ソース内容と診断表示

`PersistentStorage::getFileContent` は保存内容があればそれを返し、なければ現在のファイルを読む。さらに診断キャッシュ利用中の `StorageCache` は、診断表示用に現在のディスク内容を返す。このため「画面は常に索引時点のスナップショット」という一律の保証はない。索引時内容・現在内容・診断位置のどの組を表示するかは、再設計時に明示する。

## 正規化した比較で残す情報

数値 ID を意味上のキーに置き換え、プロジェクトルートが異なる場合は宣言したルート写像を適用できる。行の列挙順、処理時刻等も、比較プロファイルで除外理由を固定すれば無視できる。

ただし、名前階層・シグネチャ、種別、定義状態、関係の向き、位置、出現、曖昧性、アクセス、診断状態、ファイル状態を、比較器が扱わないまま「同等」と報告してはいけない。未実装の観測項目は明示的に範囲外とし、その比較結果から言えることを限定する。[ADR-0001](../adr/0001-semantic-observations.md)

DB 比較器は読み取り専用で開き、存在しないスキーマを `setup()` で作ってから成功判定しない。知らない保存版や欠けた必須テーブルは検査エラーとする。比較器自体にも、ID の付け替えでは一致し、呼び出し先や曖昧性を変えると不一致になる例を与える。

## 保存形式を変える前の受入条件

1. 新旧の形式から同じ観測形式を取り出せる。
2. 外部索引器との保存版契約と、未対応版での失敗方法が決まっている。
3. 索引 DB の再作成方針と、ブックマークの移行・復元方針が分離されている。
4. キャッシュの再構築後に、検索・参照位置・経路・診断の契約を満たす。
5. 移行途中の障害、再実行、破損入力の扱いを別途検証する。

現行のスキーマ番号を増やすことや、全体再索引化だけでは、上記の条件を自動的に満たさない。
