# 010 入力内容観測と清掃の再実装

## 対象・入力版・実施したこと

2026-10-31（Asia/Tokyo）、source 10単位。基準コミット `4d69a44ac67d03e4117c266d491c01a7a4ba87f7` からの `working-tree` を読んだ。各内容のSHA-256をmanifestへ固定する。**前回の元ファイルは未回収であり、この記録は要件からの再実装・再検証である。**

GAP-002の内容比較と取得状態の区別、差分更新後の不要な組込み型清掃を実装した。

入力観測は値のコアとI/Oアダプターを分離した。保存内容を取得できたときはmtimeを条件にせず比較し、正常な空・保存行欠落・NULL・SQL失敗・ディスク読込失敗を区別する。CRLF／CRのLF正規化を維持し、BOMと最終改行の有無を保持する。TextAccessの変更で表面化した最終改行なしXMLの誤判定をConfigManagerで修正し、引用符を含むパスの取得にはSQL束縛変数を使った。

C++の空化後に未参照の組込み型だけが残る差を、清掃対象から参照されていた型に限定して除去した。共有される型と無関係な型を保持する試験を持つ。任意ノードの一括GCへ拡張していない。

## 注釈

### ANN-001: inline bool didSourceChange(

**根拠:** `src/lib_core/SourceChange.h`、`inline bool didSourceChange(`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 取得済み内容はmtimeに関係なく比較する。非索引依存で保存行が欠落したときだけmtime互換判定を使う。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-002: bool RefreshInfoGenerator::didFileChange(

**根拠:** `src/lib/project/RefreshInfoGenerator.cpp`、`bool RefreshInfoGenerator::didFileChange(`、manifestのSHA-256と抜粋。契約: INPUT-001, REFRESH-001。

**観測:** checkedディスク読込とchecked保存読込を純粋分類へ渡す。未来の保存mtimeより過去の変更を検出した。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-003: std::shared_ptr<TextAccess> TextAccess::tryCreateFromFile(

**根拠:** `src/lib/utility/text/TextAccess.cpp`、`std::shared_ptr<TextAccess> TextAccess::tryCreateFromFile(`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 正常な空と失敗nullを区別し、CRLF/CRをLFへ正規化して最終改行の有無を維持する。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-004: sourcetrail::core::SourceContent SqliteIndexStorage::tryGetStoredFileContentByPath(

**根拠:** `src/lib/data/storage/sqlite/SqliteIndexStorage.cpp`、`sourcetrail::core::SourceContent SqliteIndexStorage::tryGetStoredFileContentByPath(`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 束縛変数でパスを照合し、Available/Missing/Null/ReadErrorを分離。長さ付き読込でNUL切詰めを防ぐ。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-005: std::shared_ptr<TextAccess> PersistentStorage::getFileContent(

**根拠:** `src/lib/data/storage/PersistentStorage.cpp`、`std::shared_ptr<TextAccess> PersistentStorage::getFileContent(`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 取得済みの空内容を現在ディスク内容で補完しない。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-006: bool ConfigManager::load(

**根拠:** `src/lib/utility/ConfigManager.cpp`、`bool ConfigManager::load(`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 最終LFなしのXMLでもTinyXMLの実エラー状態を確認してロードできる。初回E2E停止の原因を補修した。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-007: "content_cases"

**根拠:** `tests/input_observation/fixtures/expected.json`、`"content_cases"`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** mtime同一/逆行、touch、空切詰め、最終改行削除、保存行欠落/NULL、空から追加の8ケースを解析出力とは独立に記述。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-008: CREATE TEMP TABLE builtin_id_to_check

**根拠:** `src/lib/data/storage/sqlite/SqliteIndexStorage.cpp`、`CREATE TEMP TABLE builtin_id_to_check`、manifestのSHA-256と抜粋。契約: STORAGE-002。

**観測:** 清掃対象から参照された組込み型だけを候補に記録し、最後の出現・辺が消えたものを削除する。全ノードのGCには拡張しない。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-009: REQUIRE(db.storage.isNode(builtin) == shared)

**根拠:** `src/test/StorageCleanupContractTestSuite.cpp`、`REQUIRE(db.storage.isNode(builtin) == shared)`、manifestのSHA-256と抜粋。契約: STORAGE-002。

**観測:** 最後の組込み型参照の削除、共有参照の保持、無関係な組込み型の保持を確認する。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-010: ContentChangesDetected

**根拠:** `docs/contracts/formal/SourceObservation.tla`、`ContentChangesDetected`、manifestのSHA-256と抜粋。契約: INPUT-001。

**観測:** 正常モデル1152 distinct statesを探索。mtimeゲート変異は指定不変条件ContentChangesDetectedで失敗。

**未確定点:** 有限の観測値モデルであり、実ファイルシステム/SQLite実装全体を証明しない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

## 検証記録

| 実行した確認 | 結果 | 証跡と観測範囲 |
| --- | --- | --- |
| Pixiによるネイティブ全体ビルド | 成功 | 依存固定後のC++／Python有効Linuxビルド |
| `ctest --test-dir build/pixi -R '^cpp-contracts$'` | 39件、65,801 assertions成功 | [生ログ](evidence/cpp-contracts.txt)。入力分類、保存、位置、終了状態、Modern設定等 |
| `python -m pytest tests/input_observation` | 28件成功 | [生ログ](evidence/input-e2e.txt)、[JUnit](evidence/input-e2e.xml)。新しい独立期待と実アプリ |
| 既存 `legacy`／C++回帰／C++ E2E／Python回帰／Python E2E | 608／7／3／4／4件成功 | [生ログ](evidence/existing-suites.txt)。最後2群はpytestケース数 |
| SourceObservation正常・変異 | 正常1,152 distinct、指定反例を検出 | [結果](evidence/formal-summary.json)。変異はContentChangesDetected違反 |
| PythonOutputValidation正常・変異 | 正常20 distinct、指定反例を検出 | 同結果。変異はNoPublicationAfterInvalidOutput違反 |

原文ログの絶対パスは実行時の位置を示す。再現コマンド・失敗後の修正・適用範囲は[検証記録](evidence/verification.json)にも保存する。失敗した先行試行を成功として数えず、最終結果を記録した。C++試験内assertion数とpytestケース数は混ぜて合計しない。

## 次の作業と受入条件

レビューでは、人工期待が解析結果から機械生成されたものではないこと、異常出力が旧索引を保持すること、同一入力で更新と全体再構築が一致することを確認する。全入力の原子的取得、DBファイル公開のクラッシュ原子性、GUI・Windows/macOS、一般Custom全体の意味妥当性は別課題として保持する。内容を保存しない非索引依存ではmtimeの互換判定が残る。

新版言語の統合と最終verifyは012で記録する。このバッチの旧解析器成功を新版の対応能力へ読み替えない。

## レビュー状態

担当エージェントの実装検証と親担当の証跡照合を実施。ユーザー側レビューは未実施でpending。新しい混在・保存境界の独立レビューは012の証跡から追跡する。実GUI、画像注釈、他OSの試験を行ったとはしない。
