# 008 — 外部索引器の失敗境界と候補破棄の再構成

作業日: 2026-10-30（Asia/Tokyo）。基準コミットは `78e63759709be5a2f9380f3c4b0f92cc48dfd4ed`。
対象は10 source単位。画像、実GUI、ユーザー側ローカルエージェントのレビューを実施した記録ではない。

## 目的と判断

[007の人工対象と旧実装の失敗](../007-external-indexer-failure-baseline/report.md) を使い、外部索引器が起動できない、または非ゼロ終了した場合の誤った成功扱いを修正した。
実行結果の方針を標準C++の小さい値型へ分離し、並行更新・DB・Qt・プロセスの接続は既存のアダプターへ残す。
判断は [ADR-0007](../../../adr/0007-external-indexer-outcomes.md)、観測可能な約束は [EXECUTION-001](../../../contracts/external-indexing.md) にまとめた。

| 設計上の狙い | 変更した責務・境界 | 実際の受入条件 |
| --- | --- | --- |
| 単一責務・再利用性 | 成否分類と集計はQt・Boost・SQLite・LLVMを必要としない値処理 | 独立C++ビルド、3コマンドの結果27通り×完了順6通りの162組合せ |
| 依存の向き・可搬性 | 実行アダプターが値処理を利用し、mutexは実行ごとの状態ラッパーに置く | 8スレッド・480開始／確定の集計 |
| KISS・DRY | Python／Custom共通の実行経路で一度だけ分類し、同じ結果を完了・通知へ渡す | 実CLIと既存Python成功系の両方を照合 |
| 終端の一貫性 | プロセス成否とスケジューラーの継続を分ける | 失敗候補を破棄し、後始末を完了してからCLI終了1 |
| 意味の継続性 | 正常系は保存観測を保持し、失敗時の誤成功は明示的に修正 | C++／Pythonの全14観測一致と、旧失敗基準からの意図した差 |

`STATE_SUCCESS` はこのタスク列を後始末まで続けるための値であり、外部索引器が成功したという通知ではない。
プロセスが終了0でstderrを書いた場合や、グラフを一切書かなかった場合は従来どおりプロセス成功として扱う。
構文診断、出力の完全性、プロセス成否を一つのboolへ混ぜない。

## 人工対象で観測した変化

`TOY-EXTERNAL-001` は実アプリのCustom Source Groupから人工プログラムを起動する。
プログラムが書くmode・source・cwd・arguments・PID・exitのreceiptで実行内容を確認し、件数だけでは判定しない。
直列／並列の保持試験は、実C++解析器で採用済み索引を作ってから失敗する更新を行う。
再試行も実CLIを起動し、成功した置換結果を別ディレクトリのクリーン再構築と比較する。

| 観測 | 旧実装（007） | 改善後 |
| --- | --- | --- |
| 存在しない実行ファイル | CLI0、成功1/1 | CLI1、成功0/1、候補不採用 |
| 実際に終了7を返す対象 | CLI0、成功1/1 | CLI1、成功0/1、候補不採用 |
| stderrを出して終了0／無出力で終了0 | CLI0、成功1/1 | 同じプロセス成功、空のschema25グラフ |
| 失敗1件＋成功1件、直列／並列 | CLI0、成功2/2 | CLI1、成功1/2、両コマンドの実行記録あり |
| 実C++を含む更新が失敗 | CLI0、成功3/3、旧索引が候補に置換 | CLI1、成功2/3、採用済み全観測を保持 |
| その後に両外部コマンドを成功へ変更 | 再試行は成功 | CLI0、成功3/3、旧関数消去・新関数出現・clean結果一致 |

6ケース＋直列／並列それぞれseed・失敗・retry・cleanの4段階で、実CLIは計14回実行した。
各保持系列は12個の受入条件を満たした。[実行観測](evidence/external-indexer/summary.json) と全ログ・スナップショットを保存する。
再試行は別のCLIプロセスであり、同一GUIプロセス内の再試行を実証したことにはしない。

## 注釈

各単位の検索用シンボル、短い抜粋、実ファイルのSHA-256、契約IDは [manifest.json](manifest.json) に収録する。

### ANN-001 — `classifyExternalProcess`

対象: `src/lib_core/ExternalIndexerOutcome.h`。契約: EXECUTION-001, PORTABILITY-001。

**確認したこと:** 外部プロセスの分類と開始・確定・成功・失敗の計数を標準C++の値処理に分離。後続成功で失敗は消えない。

**未確認・限界:** コマンド識別子、ワーカーjoin、出力の妥当性はこの値型の責務ではない。

**次の作業:** 別言語へ移す場合は同じ独立期待と順序入力へ接続する。

### ANN-002 — `class ExternalIndexerRunState`

対象: `src/lib/data/indexer/ExternalIndexerRunState.h`。契約: EXECUTION-001。

**確認したこと:** 実行ごとの状態とmutexをアダプターに置き、480回の並行開始・確定で値を照合した。

**未確認・限界:** 任意のスレッドスケジュールや例外中断の証明ではない。

**次の作業:** 取消を実装する前に確定済みと未確定を分けた終端契約を設計する。

### ANN-003 — `TaskExecuteCustomCommands::runIndexerCommand`

対象: `src/lib/data/indexer/TaskExecuteCustomCommands.cpp`。契約: EXECUTION-001, PROCESS-001。

**確認したこと:** プロセス結果を共通分類し成功数への加算を成功時だけに限定。全ワーカーjoin後、失敗出力のマージとPython後処理を行わない。

**未確認・限界:** 通常の出力パイプ待機・タイムアウト実装は変更していない。

**次の作業:** OSプロセス制御は独立した障害対象と期限の契約で追加する。

### ANN-004 — `TaskFinishParsing::doUpdate`

対象: `src/lib/data/TaskFinishParsing.cpp`。契約: EXECUTION-001, PUBLICATION-001。

**確認したこと:** 失敗候補を問い合わせ・最適化・採用確認に渡さず、破棄とダイアログ解除を要求して後始末を継続する。

**未確認・限界:** 実GUI操作と同一GUIプロセス内の再試行は未実測。

**次の作業:** GUIの操作可能状態と進捗表示を実画面で観測するE2Eを追加する。

### ANN-005 — `Project::buildIndex`

対象: `src/lib/project/Project.cpp`。契約: EXECUTION-001, PUBLICATION-001。

**確認したこと:** 候補処分と終端通知を同じapp schedulerに順に追加し、通知の先行を防ぐ。

**未確認・限界:** 削除失敗やプロセスクラッシュを含む公開原子性は対象外。

**次の作業:** renameと削除の障害注入を別の公開契約で設計する。

### ANN-006 — `QtCoreApplication::handleMessage`

対象: `src/lib_gui/qt/QtCoreApplication.cpp`。契約: EXECUTION-001, PROCESS-001。

**確認したこと:** メッセージの終了値を値で保持し、Qtメインスレッド上のexitへ渡す。CLIの実行で終了1を確認した。

**未確認・限界:** 全OS・全Qt版の実行結果ではない。

**次の作業:** 対応OSのプロセス／イベントループ確認を能力表へ追加する。

### ANN-007 — `QtDialogView::clearDialogs`

対象: `src/lib_gui/qt/view/QtDialogView.cpp`。契約: EXECUTION-001。

**確認したこと:** 既存のQtスレッド内コールバックでウィンドウ、タスクバー進捗、UIブロックを解除する。

**未確認・限界:** Windows表示はソース読解のみで実行済みとしない。

**次の作業:** 実GUI検証では三つの解除を別々に観測する。

### ANN-008 — `read_index_observation`

対象: `tests/external_indexer/harness.py`。契約: EXECUTION-001, GRAPH-001。

**確認したこと:** 実CLIの失敗・保持・再試行を観測し、未初期化の空DBと採用済み意味スナップショットを区別する。

**未確認・限界:** 人工索引器はグラフを書かず、終了0を完全索引と扱わない。

**次の作業:** 出力能力交渉を設計するとき、別の不正出力トイを作成する。

### ANN-009 — `NoPublicationAfterFailure`

対象: `docs/contracts/formal/ExternalIndexing.tla`。契約: EXECUTION-001。

**確認したこと:** 2〜3コマンドの開始・確定・候補処分・後始末・通知を374到達状態で検査した。

**未確認・限界:** C++との機械的refinement証明、任意個数、進行性を保証しない。

**次の作業:** 取消や期限の状態を導入する変更時にモデルと負例を先に拡張する。

### ANN-010 — `external-indexing-negative-control`

対象: `script/verification/check_models.py`。契約: EXECUTION-001, REFRESH-001。

**確認したこと:** 既存更新モデルと新実行モデルを同じ固定版TLCで検査。負例は指定の不変条件違反を要求する。

**未確認・限界:** モデル検査の成功だけからアダプターやOSの正しさを推論しない。

**次の作業:** 新モデル追加時にも構文エラーや別の違反を成功にしない負例を維持する。

## 最終の実行結果

```sh
SOURCETRAIL_TOY_BASELINE=/absolute/path/to/build/toy-projects/before-external-outcomes/summary.json \
  pixi run --locked verify
```

終了コードは **0**。全12 CTestスイートが成功した。
[実出力](evidence/verify.log)、[JUnit](evidence/ctest-results.xml)、[コマンド・件数・ソースハッシュ](evidence/verification.json) を保存した。

| CTestスイート | ケース数 | 種類 | 結果 |
| --- | ---: | --- | --- |
| external-indexer-e2e | 31 | pytest | 成功 |
| toy-projects | 30 | pytest | 成功 |
| legacy | 608 | Catch | 成功 |
| cpp-contracts | 26 | Catch | 成功 |
| verification-contracts | 125 | pytest | 成功 |
| cpp-regression | 7 | Catch | 成功 |
| cpp-e2e | 3 | Catch | 成功 |
| python-regression | 4 | pytest | 成功 |
| python-e2e | 4 | pytest | 成功 |
| core-refresh-contracts | 単独プログラム | standalone C++ | 成功 |
| core-command-contracts | 単独プログラム | standalone C++ | 成功 |
| core-execution-contracts | 単独プログラム | standalone C++ | 成功 |

Catch／pytest合計は **838ケース**。単独C++プログラム3本や有限入力数をこのケース総数へ混ぜない。
Python regression／E2Eはマーカーで相互に異なる4ケースずつを選択する。CTestでskipしたスイートはない。
新E2Eの31ケースは、実アプリの8シナリオと観測器の23ケースを合わせたもの。
最終E2Eの前に実行した観測器単独の [23ケース](evidence/harness-controls.log) は重複計上しない。

従来トイはC++／Python各7段階の必要な事実、実行内8比較、変更前との14比較を通過した。
[最終観測](evidence/successful-toys/summary.json) と、005に保存済みの基準に対する各スナップショットのバイト一致・SHA-256を `verification.json` に記録する。
意味比較器 `semantic_graph.py` 自体は変更していない。
実行バイナリーのSHA-256は `4cf3f921f83c741cab2f305359ea92950a9c689e2bb021dded3b420a5f703dbc`。
生成compile_commandsでは既存LLVM11解析器のGNU C++14と、アプリ／試験のGNU C++17の境界を保持している。

レポート追加後の [文書検査](evidence/docs-final.log) は33 Markdown・20契約・6言語プロファイル・8レポート、エラー0。
さらにGit indexだけを別ディレクトリへ取り出した [公開対象の検査](evidence/index-export-docs.log) も同じ件数で成功した。
これはリンク・台帳・証跡の収録確認であり、意味的な正しさの代わりにはしない。

### 形式モデルと移植適合

[TLCの実結果](evidence/formal-summary.json) は全5構成で期待した判定になった。
既存更新モデルは混合関係522,720状態、単一関係69,120状態を全探索し、既存負例は指定した共有依存の不変条件に違反した。
新しい外部実行モデルは **374 distinct／656 generated／pending0**。
失敗を後続成功で消してしまう変異版は **178 distinct／270 generated** で `NoPublicationAfterFailure` 違反を検出した（TLC終了12）。
変異版のエラーは想定した負例の検出であり、モデル構文エラーを成功としていない。
2〜3コマンドの有限安全性の確認であって、C++との機械的refinement、任意個数、進行性、OS上の停止や公開原子性の証明ではない。

独立したportability環境でも [3コア試験](evidence/standalone-core-results.xml) が成功した。
既存の更新コアはC++本番実装とRust参照移植で、それぞれ **32,778入力**（手書き10＋有限32,768）について独立期待値へ一致した。
[版・入力・結果](evidence/portability-summary.json) を保存する。今回追加した外部実行方針のRust移植やRustソース索引器を実装したという意味ではない。

## 独立レビューと途中の失敗

[assistant側独立レビュー](evidence/integration-review.json) では次の3点を発見し、修正後に再確認した。

| 指摘 | 修正 | 確認の範囲 |
| --- | --- | --- |
| 失敗時にCustom用進捗ダイアログが残る | clearDialogsへ統一し、Qt側でタスクバー進捗とUIブロックも解除 | ソース読解と追跡ダイアログのC++試験。実GUI／Windowsは未実測 |
| 成功receiptの重複で失敗対象の実行を偽装できる | 期待source集合・一意性・mode・exit・args・cwd・PIDを検査し、失敗／retry両方へ適用 | 元の偽陽性入力の拒否、負例5件、旧基準のreceipt再照合 |
| Linux専用E2Eが全OSへ登録される | CTest登録をLinuxかつC++有効に限定 | CMake読解。全OS対応を主張しない |

最初の全ゲートは11スイートが成功し、新E2Eが初回失敗後のmain DBをschema25として読んでしまい失敗した。
[原文ログ](evidence/first-verify-failed.log) を保存する。この時点の13成功・8 setup errorを最終成功へ混ぜない。
`Project::load` による初期化は既知の空テーブルだけを作るため、候補を正しく破棄しても未版付けmain DBが存在し得る。
観測器へ `absent`／`uninitialized-empty`／`schema-25` の識別を追加した。

未初期化の例外は、既知13表と列名の完全一致、metaも含め全0行、既知occurrence自動索引だけ、SQLite integrity／foreign-key検査成功に限定する。
意味スナップショットは合成せず `None` を返す。新規失敗でschema25の候補採用は拒否し、採用済み索引の保持には実際のseedとの一致を要求する。
未版付けデータ、未知版、列欠落、余計なtable／view／index、破損ファイルを負例に追加した。
独立レビューも実ソースの13 CREATE TABLE文を使うメモリDBでこの境界を確認した。
その後、全ゲートを最初から再実行し、上記の成功を得た。本番処理を空DBのために緩めた変更はない。

## 次の作業と受入条件

| 優先 | 契約・対象 | 必要な入力 | 作業と受入条件 |
| --- | --- | --- | --- |
| 1 | GAP-002／入力変更検出 | 同一mtimeで内容変更、空ファイル、保存内容なし、読込失敗の人工対象 | 時刻・内容・読込可否を区別し、増分結果がclean結果へ一致すること。変更検出と既存正規化を別々に評価 |
| 2 | GAP-003／位置規約 | 非ASCII・絵文字・CRLF、各解析器が返す位置 | byte／Unicode／UTF-16列の変換を宣言し、ソース参照の同じ範囲へ正規化できること |
| 3 | GAP-005／外部実行の残り | 期限超過、取消、不正・未完成の出力、版不一致 | 状態契約を先に追加し、終端後の後始末・採用可否・通知を実障害対象と形式負例で確認 |
| 4 | 言語能力・新しい解析器 | 新Python／C++の版、構文一覧、固定環境 | 共通能力の意味観測を維持し、新能力は専用トイとプロファイルで明示 |
| 5 | Rustソース索引 | Cargo／edition／trait・impl／マクロ位置の仕様 | 言語アダプターの入出力契約と専用トイを追加し、共通の探索操作へ適合させる |
| 6 | GUI・OS・公開耐障害性 | 実GUI、Windows/macOS、DB操作失敗とクラッシュの注入 | CLI／保存グラフの一致から推測せず、それぞれの観測を実測する |

[改善計画](../../../architecture/evolution-plan.md) と契約台帳を入口に、対象版・必要な入力・受入条件を固定して次の少数単位を調査する。
GAP-005は部分改善であり、全ての外部実行異常や新言語対応が完了したとは扱わない。
ユーザー側ローカルエージェントのレビューは **pending**。本バッチと007の失敗基準、manifestの10単位を入力として使い、追加結果は新しいバッチへ残す。
