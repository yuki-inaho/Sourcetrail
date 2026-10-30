# 001: 契約境界の初回注釈レポート

## 対象・入力版・実施したこと

**対象はコード・形式仕様の 10 単位（source）である。画像の入力はなく、画像アノテーションは実施していない。**
本レポートは、更新計画の抽出と契約整備を進める際に、別のエージェントが意味上の境界を追えるように作成した。

基準コミットは `1bc605e8bea8d75abd87121e704c90caa380e44b`。そこから作業中の変更を含む `working-tree` スナップショットを読んでいる。
基準コミットだけを checkout しても新しい `RefreshPlan` や形式仕様は存在しない。読んだ各ファイルの SHA-256、検索シンボル、短い原文抜粋は [manifest.json](manifest.json) に保存した。

調査方法は、実装と呼び出し境界の読解、対応する契約の特定、TLC による有限状態検査、検証実行器の誤判定防止テストである。
入力分類、計画、解析・後処理、保存、問い合わせ、表示の保証を混ぜないように選定した。全ファイルの注釈や全概念の形式化を終えたという意味ではない。

## 注釈

### ANN-001: RefreshPlan::forUpdatedFiles

**根拠:** `src/lib/project/RefreshPlan.cpp` の `RefreshPlan::forUpdatedFiles`。契約: REFRESH-001, REFRESH-002。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** 更新計画は分類済みの集合と読み取り専用の依存問い合わせから、消去・索引化の集合を返す。ファイル発見や保存操作は関数の外にある。

**未確定点・範囲:** 問い合わせが同じスナップショットを見ることは呼び出し側の前提であり、新しいロックは追加していない。

**次の作業:** 入力分類と並行更新の境界を別契約として確認する。

### ANN-002: PersistentStorage::getReferenced

**根拠:** `src/lib/data/storage/PersistentStorage.cpp` の `PersistentStorage::getReferenced`。契約: REFRESH-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** include と import の推移閉包を別々に計算して和集合にする。混在した辺を一つの閉包として扱ってはいない。

**未確定点・範囲:** 混在閉包への変更が将来必要かは未決定。現在の同等性の基準には含めない。

**次の作業:** 新しい言語を追加するとき、依存辺の種類と更新への写像を明示する。

### ANN-003: RefreshInfoGenerator::didFileChange

**根拠:** `src/lib/project/RefreshInfoGenerator.cpp` の `RefreshInfoGenerator::didFileChange`。契約: INPUT-001, REFRESH-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** ディスクの mtime が保存値より新しい場合にだけ内容比較する。更新計画の集合計算の正しさは、変更検出の完全性を保証しない。

**未確定点・範囲:** 同時刻・逆行時刻の変更、読み取り中の編集は今回のモデル対象外。

**次の作業:** 時刻が進まない変更を検出する契約と実例を先に作り、検出方式の変更を別途評価する。

### ANN-004: SourceGroup::containsSourceFilePath

**根拠:** `src/lib/project/SourceGroup.cpp` の `SourceGroup::containsSourceFilePath`。契約: SOURCE-GROUP-001, REFRESH-003。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** 包含判定を集合の membership として実装し、除外操作は getSourceFilePathsExcept に分けた。旧 filterToContainedSourceFilePath は除外の互換入口として残る。

**未確定点・範囲:** これは旧包含判定の誤りを直す意図的な振る舞いの変更。更新計画抽出の同等性とは区別する。

**次の作業:** 単一・複数・空のソース集合と、Python の全体更新への切替えをローカルレビューで確認する。

### ANN-005: Project::swapToTempStorageFile

**根拠:** `src/lib/project/Project.cpp` の `Project::swapToTempStorageFile`。契約: PUBLICATION-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** 旧 DB を削除してから一時 DB を rename する。形式モデルの一遷移を根拠に、この公開処理の原子性を主張できない。

**未確定点・範囲:** 削除後・rename 前後のクラッシュ回復は未検証で、今回変更していない。

**次の作業:** 失敗時の保持・復旧契約を定め、障害注入と起動時回復の受入試験を作る。

### ANN-006: SqliteIndexStorage::addNodes

**根拠:** `src/lib/data/storage/sqlite/SqliteIndexStorage.cpp` の `SqliteIndexStorage::addNodes`。契約: NAME-001, STORAGE-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** ノード再利用は serializedName の索引を使い、既存ノードの型を更新する場合がある。数値 ID は意味上の恒久キーとして比較できない。

**未確定点・範囲:** 言語・パッケージ・ビルド構成を横断する名前衝突と将来の移行規約は未確定。

**次の作業:** Rust や解析器更新前に同一性規約と衝突例を追加し、ブックマーク復元も別に評価する。

### ANN-007: ParseLocation::isValid

**根拠:** `src/lib/data/parser/ParseLocation.cpp` の `ParseLocation::isValid`。契約: LOCATION-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** isValid は fileId の真偽だけを確認する。列単位、行範囲、始点と終点の順序の完全な検証ではない。

**未確定点・範囲:** Unicode・改行・マクロ展開で全アダプターが同じ位置規約になることは未証明。

**次の作業:** 各アダプターの座標単位と共通の観測座標を定義し、Unicode とマクロの対応試験を加える。

### ANN-008: TaskExecuteCustomCommands::runPythonPostProcessing

**根拠:** `src/lib/data/indexer/TaskExecuteCustomCommands.cpp` の `TaskExecuteCustomCommands::runPythonPostProcessing`。契約: RELATION-001, LANGUAGE-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** Python の後処理は未解決位置から候補の辺を作り、IS_AMBIGUOUS 成分を付ける。保存辺の本数だけでは確定参照と推測参照を区別できない。

**未確定点・範囲:** Python の完全・浅い解析の能力差や新版への互換性は、単一の試験ランナー版から推測できない。

**次の作業:** 能力プロファイルごとに診断・位置・曖昧性を比較し、既存部分と新しい構文能力を別に受け入れる。

### ANN-009: getGraphForTrail

**根拠:** `src/lib/data/storage/StorageAccess.h` の `getGraphForTrail`。契約: QUERY-001。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** 問い合わせには始点・終点、ノード型・辺型、深さ、方向などの条件がある。保存 DB の意味比較だけでは問い合わせ結果の同等性を保証できない。

**未確定点・範囲:** 候補順位、キャッシュ、GUI の表示や履歴、外部エディター往復は本バッチでは実行していない。

**次の作業:** StorageAccess の問い合わせを意味上のキーで観測する適合試験を先に作り、GUI 試験を段階的に加える。

### ANN-010: Refinement

**根拠:** `docs/contracts/formal/RefreshPlan.tla` の `Refinement`。契約: REFRESH-001, REFRESH-002。ファイル全体の SHA-256 はマニフェストを参照。

**観測:** 途中の計算を隠した結果観測が、抽象的な更新計画の許す状態列に含まれることを有限モデルで確認する。共有依存を消す変異モデルは反例を返す。

**未確定点・範囲:** C++ の自動翻訳や任意サイズの証明ではなく、ファイル分類・DB 公開・並行ワーカー・完了性は対象外。

**次の作業:** モデルの前提を変更するときは C++ の実装試験と両方を実行し、新しい有限範囲と反例を記録する。

## 検証記録

| 確認 | このバッチでの結果 | 証跡 | 解釈 |
| --- | --- | --- | --- |
| TLC の include/import モデル | 522,720 状態、違反なし | [ログ](evidence/refresh-mixed.log) | 3 ファイル、各関係 2 非自己辺以下 |
| TLC の単一関係モデル | 69,120 状態、違反なし | [ログ](evidence/refresh-single-relation.log) | 3 ファイルの全 64 グラフ |
| 共有依存保護を外した変異モデル | 指定した不変条件違反を検出 | [反例](evidence/refresh-negative-control.log) | 任意の実行失敗を期待成功としていない |
| モデル実行器の誤判定防止テスト | 14 passed | [コマンドと結果](evidence/verification.md) | 検証器の失敗判定、ツールのハッシュ確認 |
| 文書検査器と記録形式 | 27 passed、文書検査でエラー 0 | [コマンドと結果](evidence/verification.md) | 根拠参照・履歴・壊れたリンクの誤受理防止 |
| リポジトリ内スキルの形式検査 | 成功 | [コマンドと結果](evidence/verification.md) | 独立エージェントによる実運用評価は別途必要 |
| 全 C++／Python 回帰・E2E と統合確認 | この注釈バッチでは集計対象外 | 統合検証の記録を別途参照 | 上記の有限モデル結果から推測しない |
| 画像、実 GUI、ユーザー側ローカルエージェントレビュー | 未実施 | 入力・実行の事実なし | 実施済みとは記録しない |

TLC の設定、配布物のハッシュ、モデルのハッシュ、実行引数は [formal-summary.json](evidence/formal-summary.json) に保存した。
TLC ログのホスト表示時刻は収集環境の時刻であり、レポート日付は Asia/Tokyo の 2026-10-30 である。

## 次の作業と受入条件

| 優先 | 契約・対象 | 必要な入力 | ローカルエージェントに渡す作業 | 受入条件 |
| --- | --- | --- | --- | --- |
| 1 | SOURCE-GROUP-001、REFRESH-003 | 本変更のコミット、基準コミット、関連試験 | membership 修正と除外別名の互換性、Python 更新判定の呼び出しを独立レビューする | 意図した修正と維持した挙動が分かれ、空・単一・複数・範囲外の例を確認できる |
| 2 | PUBLICATION-001 | 公開処理と復旧方針の設計 | 削除・rename の間を含む失敗状態と復旧可能性を設計する | 旧索引または新索引の採用状態が識別でき、障害注入で回復を確認する |
| 3 | INPUT-001、LOCATION-001 | 編集時刻・Unicode・マクロの例 | 変更検出と座標規約の試験を独立単位で追加する | 同時刻変更と位置の誤対応を検知し、未対応条件を明示する |
| 4 | LANGUAGE-001、NAME-001、RELATION-001 | 対象 Python/C++ 版、Rust の初期能力、解析器候補 | 共通能力の比較と新能力の受入例を分け、同一性・依存・曖昧性の写像を確定する | 版・モード・構文範囲が固定され、未実装の能力を対応済みと表示しない |
| 5 | QUERY-001 | StorageAccess の代表問い合わせ | 検索順位・方向・深さ・フィルター・キャッシュの観測試験を設計する | DB 意味比較と問い合わせの適合性を別々に判定する |
| 6 | REFRESH-001、REFRESH-002 | 形式仕様、C++ 関数、独立した期待値 | モデルの前提と C++ の責務境界を突き合わせる | 固定スナップショット等の前提と、まだ形式化していない処理を列挙できる |

## ローカルレビューの開始手順

1. 本レポートを含むコミットを取得し、対象の作業ツリーに別の変更がないか確認する。
2. マニフェストの `source_revision` と入力ハッシュを読み、基準版・記録時・最新のどの内容をレビューするか明記する。
3. 契約カタログ、関連 ADR、各 `ANN-*` のソースと検証を読む。本文の結論を根拠として再利用せず、コードまたは実行で確認する。
4. `pixi run --locked verify-docs`、関連する実行試験、必要なら `pixi run -e formal --locked verify-models` を実行する。
5. 誤り・未確定点・追加作業を、次の `NNN-topic` バッチに根拠付きで保存する。過去のマニフェストのハッシュを書き換えない。

## レビュー状態

本バッチの注釈・形式モデル実行は今回の作業エージェントが行った。
**ユーザー側のローカルエージェントによる独立レビューは pending。** 実施したかのような承認・合格記録は作成していない。
関連する全体の未解決事項は [改善順序と GAP 一覧](../../../architecture/evolution-plan.md) を参照する。
