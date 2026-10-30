# 002: 変更検出・索引公開・経路問い合わせの独立レビュー

## 対象・入力版・実施したこと

**初回バッチの ANN-003・ANN-005・ANN-009 を、assistant 側の別担当が実コードから再確認した。3 件の関数単位の source レビューであり、ユーザー側のローカルエージェントによるレビューは未実施である。**

元の [001-contract-boundaries](../001-contract-boundaries/report.md) とそのマニフェストは変更していない。本バッチの ID はローカルに `ANN-001` から採番し、次のように対応させる。呼び出し元・下位実装・既存試験は各関数の根拠として読むが、追加の注釈件数には数えない。

| 本バッチ | 元バッチ | 関数単位 | 契約 | 読解結果 |
| --- | --- | --- | --- | --- |
| ANN-001 | ANN-003 | `RefreshInfoGenerator::didFileChange` | INPUT-001, REFRESH-001 | mtime 条件を確認。保存内容の有無と行単位比較を補足 |
| ANN-002 | ANN-005 | `Project::swapToTempStorageFile` | PUBLICATION-001 | 削除後 rename を確認。失敗を bool で返す下位 API の戻り値を確認していない |
| ANN-003 | ANN-009 | `PersistentStorage::getGraphForTrail` | QUERY-001 | 宣言から実装と呼び出し側まで確認。深さ・方向・型フィルター・表示前の加工を補足 |

基準コミットは `1bc605e8bea8d75abd87121e704c90caa380e44b`、ブランチは `refactor/semantic-contracts`、記録モードは `working-tree`。このコミットから進行中の未コミット変更を含む。入力内容は [manifest.json](manifest.json) と [source-review.json](evidence/source-review.json) の SHA-256 で識別する。元バッチの `RefreshInfoGenerator.cpp` と `StorageAccess.h` の全ファイルハッシュは今回と一致する。`Project.cpp` は別担当による `buildIndex` の変更が入り全体のハッシュが異なるため、過去のハッシュを置き換えず、新しい入力版として記録した。対象の `swapToTempStorageFile` 本体は基準コミットの内容と一致することを別途確認した。

調査にはリポジトリ内の `annotate-contract-batch` を使用し、文書入口、契約カタログ、ADR-0001・ADR-0002・ADR-0003、元レポート、実装と必要な呼び出し境界を読んだ。実行した検査は後述の入力照合と `verify-docs`。本担当は C++ の実行試験、障害注入、全ビルド、TLC、実 GUI、画像アノテーションを行っていない。他担当の検証結果を本担当の実行結果として記載しない。

## 注釈

### ANN-001: mtime 条件と内容比較の範囲

**根拠:** [RefreshInfoGenerator.cpp](../../../../src/lib/project/RefreshInfoGenerator.cpp) の `RefreshInfoGenerator::didFileChange` と `getRefreshInfoForUpdatedFiles`。補助根拠は [FileSystem.cpp](../../../../src/lib/utility/file/FileSystem.cpp)、[TextAccess.cpp](../../../../src/lib/utility/text/TextAccess.cpp)、[PersistentStorage.cpp](../../../../src/lib/data/storage/PersistentStorage.cpp)、[RefreshInfoGeneratorTestSuite.cpp](../../../../src/test/RefreshInfoGeneratorTestSuite.cpp)。各ファイルの読解範囲とハッシュは `source-review.json` にある。契約は INPUT-001、REFRESH-001。

短い原文抜粋:

```cpp
if (diskFileInfo.lastWriteTime > info.lastWriteTime)
```

**観測:** 元 ANN-003 の「mtime が保存値より新しい場合だけ内容比較へ進む」はコードに沿っている。条件の内側でも経路が分かれる。

| `didFileChange` の条件 | 戻り値・処理 |
| --- | --- |
| ディスク mtime が保存値以下 | 内容を読み比べず `false` |
| mtime が新しく、`hasContentForFile` が `false` | 内容比較なしに `true` |
| mtime が新しく、保存内容があり、行数またはいずれかの行が異なる | `true` |
| mtime が新しく、保存内容があり、全行が一致する | `false` |

`hasContentForFile` は保存された `TextAccess` の行数が 0 より大きいかを見ている。比較は生のファイルバイト列ではなく `getAllLines()` の配列である。ディスク側の `TextAccess::readFile` は `safeGetline` で CR/LF を扱い、行末として LF を付け直す。したがって「内容比較」を、すべてのバイト差の検出と読み替えるべきではない。

呼び出し元は、ファイルの所属・存在・indexed 状態を確認して `changedFilePaths` 等へ分類した後に `RefreshPlan::forUpdatedFiles` を呼ぶ。削除の扱いも呼び出し元にある。`didFileChange` の戻り値と最終的な再索引集合は同一の観測ではなく、依存関係など別の理由で再索引される場合も分ける必要がある。

カタログが参照する既存の代表試験 `indexed changed sourcefile that is toindex` と共通 fixture を読んだ。この fixture は保存時刻に前日または翌日を設定して状態を作る。これを読んだことから、同一時刻の内容差や読み取り競合の試験まで存在・成功すると主張しない。

**推論:** 既知・存在・indexed のファイルで同一または過去の mtime を保ったまま内容が変わると、この関数だけでは変更と判定されない。依存変更など別の再索引理由がない入力を用意すれば、検出の限界を更新計画との接続点で調べられる。これは制御フローからの推論であり、今回その fixture は実行していない。

**未確定点:** 同時刻・逆行時刻の変更、空内容の保存、CR/LF のみの差、読込失敗、入力読込中の編集の期待値と実測結果は未確定。mtime ゲートを改善することは現行挙動との単純な等価性とは別に受け入れる必要がある。

**次の作業:** 下記 F1 の固定 fixture と観測項目を作り、現行の分類を記録してから、新しい変更検出の受入条件を決める。

### ANN-002: 公開順序と失敗の報告経路

**根拠:** [Project.cpp](../../../../src/lib/project/Project.cpp) の `swapToTempStorageFile`、`swapToTempStorage`、`load`、および [FileSystem.cpp](../../../../src/lib/utility/file/FileSystem.cpp) の `remove` と `rename`。契約は PUBLICATION-001。カタログ上の状態は `planned` のままである。

短い原文抜粋:

```cpp
FileSystem::remove(indexDbFilePath);
FileSystem::rename(tempIndexDbFilePath, indexDbFilePath);
```

**観測:** 元 ANN-005 の順序の指摘は正しい。さらに、両操作の戻り値を確認せず、`std::exception` を捕捉したときだけ `false` を返し、それ以外は `true` を返す。

下位の `FileSystem::remove` は `boost::filesystem::remove(path, ec)` を使い、結果の bool を返す。`FileSystem::rename` には、移動元がないか移動先が既にある場合、例外を投げず `false` を返す分岐がある。この bool を公開側が捨てていることは、原子性とは別の確認項目になる。

呼び出し元の `swapToTempStorage` はストレージを reset し、wrapper が `false` なら未ロード状態にする。`true` なら所定の DB パスでストレージを開き、キャッシュを構築してロード済み状態へ進む。

`load` には一時 DB が残った場合の分岐もある。旧 DB と一時 DB の両方がある場合は採用・破棄の選択を求め、一時 DB だけがある場合は直接 rename を呼ぶ。後者も rename の bool を確認しない。この分岐の存在は確認したが、クラッシュ復旧を実行して成功を確認したという意味ではない。

**推論:** 例外が起きず下位 API が `false` を返す条件では、wrapper が `true` へ到達し得る。例えば削除が成功せず移動先が残った場合、rename は `false` を返しても wrapper の成功値へ進む。また、一時 DB がない状態で旧 DB の削除だけが成功する条件では、その後の rename は `false` になり得る。どの状態が通常実行・競合・障害時に成立するかは、別途再現が必要である。

このため、追加の確認は「remove と rename の間で止める」だけでは足りない。**bool による失敗、例外、中断後の再起動を別々に観測する必要がある。** 今回はコードの分岐から到達可能性を指摘しており、実機でデータ喪失を再現したとは記録しない。

**未確定点:** OS ごとの使用中ファイルの挙動、取消時のストレージ寿命、クラッシュ直後に残る内容、永続化の完了、ブックマークとの整合性は未検証。既存の起動時分岐だけで旧版または新版の保持を保証できるかも未確定。

**次の作業:** F2 で失敗の通知と採用版の識別を先に固定し、障害注入を用いて公開・復旧方式を評価する。今回のレビューでは公開実装を修正していない。

### ANN-003: 経路問い合わせと呼び出し側の観測境界

**根拠:** 元 ANN-009 の [StorageAccess.h](../../../../src/lib/data/storage/StorageAccess.h) の宣言に加え、[PersistentStorage.cpp](../../../../src/lib/data/storage/PersistentStorage.cpp) の `getGraphForTrail`、[GraphController.cpp](../../../../src/lib/component/controller/GraphController.cpp) の `handleMessage(MessageActivateTrail*)`、[MessageActivateTrail.h](../../../../src/lib/utility/messaging/type/activation/MessageActivateTrail.h)、[QtGraphView.cpp](../../../../src/lib_gui/qt/view/QtGraphView.cpp)、[QtCustomTrailView.cpp](../../../../src/lib_gui/qt/view/QtCustomTrailView.cpp)、[Edge.h](../../../../src/lib/data/graph/Edge.h)。契約は QUERY-001。

短い原文抜粋:

```cpp
while (nodeIdsToProcess.size() && (!depth || currentDepth < depth))
```

**観測:** 元 ANN-009 の「保存 DB の意味比較だけでは問い合わせ結果の同等性を保証できない」は、宣言だけでなく実装・呼び出し側にも境界があることから支持できる。

| 境界 | 読んだコードの挙動 |
| --- | --- |
| 始点と終点 | `originId` があればそこから、なければ `targetId` から探索し、取得する辺の側を切り替える |
| 深さ | `depth == 0` はループ条件の深さ上限を無効にする。通常・カスタム UI の最大スライダー値も 0 に写す |
| 辺の方向 | `directed` の指定に加え、`LAYOUT_VERTICAL` の辺では探索方向の計算を反転する。対象は inheritance、override、template specialization |
| 型・非索引対象 | `nodeTypes != 0` の枝で型・定義/indexed 状態等を調べる。`nodeTypes == 0` の枝はその検査を通らない |
| 通常・カスタム入力 | 通常のメッセージは `nodeTypes=0`。カスタム UI はノード型・辺型マスクが空なら要求を送らない |
| 戻すグラフ | 探索した ID から親と辺を補い、access・ambiguity の成分を加えて返す。探索途中の集合と最終グラフを同一視しない |
| controller | `getGraphForTrail` へ `directed=true` を渡す。通常の include trail では、開始側ノードが defined の場合に undefined ノードを除く処理も行う |

`GraphController` が方向指定を固定していても、通常 UI の「前・後」が失われるという意味ではない。`QtGraphView::getMessageActivateTrail` は `originId` と `targetId` のどちらを 0 にするかで前・後を表現している。引数名だけで方向の意味を決めず、この接続まで確認した。

**推論:** 保存グラフが同じでも、深さ・方向・型マスクや controller の加工を変更すれば表示前に受け取るノード・辺が変わり得る。従って保存比較に加え、ストレージ問い合わせの戻り値と controller が加工したグラフに独立した期待値が必要である。

**未確定点:** この組み合わせを実行した結果、双方向指定、循環、到達不能な終点、空の入力 ID、両端指定で `nodeTypes=0` を API に直接渡す場合の扱いは今回検証していない。最後の組み合わせはカスタム UI の入力制約とは分けて仕様を決める。キャッシュ更新、検索順位、実 GUI の描画・履歴・外部エディター往復も対象外。

**次の作業:** F3 の小さなグラフ fixture で StorageAccess の問い合わせを先に特徴づけ、続いて controller での加工を検査する。

## 検証記録

実コマンド、対象版、終了コードと範囲は [verification.md](evidence/verification.md) に保存する。

| 確認 | 結果 | 証跡 | 解釈 |
| --- | --- | --- | --- |
| `git status --short --branch` と `git rev-parse HEAD` | 記録済み | [入力記録](evidence/source-review.json) | 既存の未コミット変更を含む作業ツリーの識別 |
| 今回の読解入力のハッシュ・抜粋、元バッチのハッシュとの比較 | 成功。12 ファイル・3 単位、抜粋の存在と公開関数本体の一致 | [確認記録](evidence/verification.md) | スナップショットと根拠文字列の照合。意味的な正しさの試験ではない |
| `/workspace/scratch/715c5c4089e4/tooling/pixi run --locked verify-docs` | 成功。終了コード 0、文書エラー 0 | [実出力](evidence/verify-docs.log) | 文書構造・契約参照・リンク等の検査 |
| C++ 実行試験、障害注入、全ビルド、TLC | 本担当では未実行 | この実施範囲の記載 | 初回バッチや他担当の結果を流用しない |
| 画像、実 GUI、ユーザー側ローカルエージェントのレビュー | 未実施 | この実施範囲の記載 | `source` 3 単位以外の実施件数に数えない |

## 次の作業と受入条件

以下は将来作業であり、実施済みの検査ではない。次の担当は対象コミットと入力ハッシュを選び、結果を新しいバッチへ保存する。

| ID・優先 | 対象契約 | 必要な入力 | 作業と実行する確認 | 受入条件 |
| --- | --- | --- | --- | --- |
| F2・高 | PUBLICATION-001 | 本バッチの `Project.cpp` / `FileSystem.cpp`、識別できる旧 DB と一時 DB、失敗を制御できる一時ディレクトリまたは API 境界 | remove の false、rename の false、rename の例外、削除直後の中断を分けて注入する。各ケースで wrapper の値、プロジェクト状態、旧/一時 DB の存在・内容、再起動後の採用版を確認する | 採用できない場合を成功として扱わない。採用版を識別でき、旧版または検証済み新版に回復できる。ブックマークの保持も独立に確認する。既存挙動の再現と修正後の合格を別に記録する |
| F1・高 | INPUT-001, REFRESH-001 | 同一内容/別内容、保存内容あり/なし、mtime が小さい/同じ/大きいファイル、依存のない既知 indexed fixture と依存あり fixture | 変更分類、`filesToClear`、`filesToIndex` を観測する。touch、削除、CR/LF のみの差、空内容、読み取り中変更も別ケースで記録する。対応する C++ テストを実行する | 各期待値を先に宣言し、時刻が進まない変更を黙って対応済みとしない。現行の限界を再現した後、改善する条件を合意した契約に従って判定する。無変更の内容を不要に変更扱いする場合も判定できる |
| F3・中 | QUERY-001 | A→B→C の CALL 経路、逆向き辺、垂直辺、親ノード、indexed/undefined ノード、循環・到達不能ノードを持つ小さな保存 fixture | `depth=0/1/2`、始点/終点、型マスク、`nodeNonIndexed`、`directed` を固定してストレージ結果を比較する。通常/カスタムメッセージと include の controller 後の結果も別に観測する | 完全な名前・シグネチャ等の意味キー、辺種別と向き、親補完と成分を保持して期待値を比較できる。数値 ID の変更を許しても欠落・余分な辺を検出する。保存比較と問い合わせ適合性を別判定にする |

F1/F2/F3 は [GAP 一覧](../../../architecture/evolution-plan.md) の INPUT・PUBLICATION・QUERY の課題を、この 3 単位で開始できる粒度にしたもの。新規の契約 ID や未実行の試験成功を追加したものではない。

## レビュー状態

assistant 側の別担当による **今回のソース読解は completed**。実施範囲と根拠は本レポート、マニフェストの `performed_review`、`source-review.json` に記録した。

**ユーザー側のローカルエージェントによる次回レビューは pending**。マニフェストの標準 `review` 欄はこの未実施レビューを表し、`performed_review` と区別する。元バッチの 10 件全体を承認したこと、F1/F2/F3 の実行試験に合格したこと、画像注釈を行ったことを意味しない。
