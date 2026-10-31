# 011 旧PythonのUTF-8位置と異常出力拒否

## 対象・入力版・実施したこと

2026-10-31（Asia/Tokyo）、source 7単位。基準コミット `4d69a44ac67d03e4117c266d491c01a7a4ba87f7` からの `working-tree` を読んだ。各内容のSHA-256をmanifestへ固定する。**前回の元ファイルは未回収であり、この記録は要件からの再実装・再検証である。**

GAP-003の保存位置変換を全ワーカー後・注入前へ接続し、不整合出力を既存索引へ公開しないようにした。

保存規約は1始まり・UTF-8バイト列・終端込み。BOM、CRLF、最終改行、次行列0、許可するゼロ幅診断・スコープを扱い、NUL、不正UTF-8、所有・内容・範囲の不整合を拒否する。変換はDB／ソースごとに一度だけ行い、途中の不正をsavepointで戻す。プロセス失敗と出力拒否件数を分けて終了通知へ渡す。

固定旧Python索引器は正常な空ファイルのfilecontentを省略する。実ファイルが空、一意の索引済みPython行、位置なし、という条件を検査した場合に限り明示的な空内容を補う。一般の保存欠落を空へ変換してはいない。

**旧Python DBは全体再索引化が必要。** ASCIIでも次行列0のスコープ表現が変わるため、過去の位置スナップショット14観測の完全一致とは報告しない。新しい保存規約でのトークン照合と、同じ版における増分／全体再構築一致を根拠にする。

## 注釈

### ANN-001: SourceRange toBytes(

**根拠:** `src/lib_core/Utf8SourceLocationMap.h`、`SourceRange toBytes(`、manifestのSHA-256と抜粋。契約: LOCATION-001。

**観測:** 旧Pythonスカラー列を厳格UTF8境界で1始まり終端込みバイトへ変換する。BOM、次行列0、空診断境界を扱う。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-002: bool SqliteIndexStorage::normalizePythonSourceLocations(

**根拠:** `src/lib/data/storage/sqlite/SqliteIndexStorage.cpp`、`bool SqliteIndexStorage::normalizePythonSourceLocations(`、manifestのSHA-256と抜粋。契約: LOCATION-001, EXECUTION-001。

**観測:** 実入力と保存内容を照合し、ID/所有/種別を保つsavepoint更新。旧ライブラリーが省略する空内容は限定条件で明示行を作る。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-003: for (const auto& output: m_pythonSourcesByDatabase)

**根拠:** `src/lib/data/indexer/TaskExecuteCustomCommands.cpp`、`for (const auto& output: m_pythonSourcesByDatabase)`、manifestのSHA-256と抜粋。契約: LOCATION-001, EXECUTION-001。

**観測:** ワーカー停止後・注入前にDB/ソース組を一回変換する。無効なら候補不採用へ進み、旧索引保持と再試行を実CLIで確認した。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-004: void observeOutput(

**根拠:** `src/lib_core/ExternalIndexerOutcome.h`、`void observeOutput(`、manifestのSHA-256と抜粋。契約: EXECUTION-001。

**観測:** 出力拒否件数をプロセス失敗件数と分離し、後続成功で失敗を消さない。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-005: std::to_wstring(outcome.invalidOutputs)

**根拠:** `src/lib/data/TaskFinishParsing.cpp`、`std::to_wstring(outcome.invalidOutputs)`、manifestのSHA-256と抜粋。契約: EXECUTION-001。

**観測:** プロセス失敗と無効出力の件数をそれぞれ通知し、共通の不採用終了経路へつなぐ。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-006: def test_python_positions_select_utf8_tokens_in_stored_content(

**根拠:** `tests/input_observation/test_input_observation.py`、`def test_python_positions_select_utf8_tokens_in_stored_content(`、manifestのSHA-256と抜粋。契約: LOCATION-001。

**観測:** BOM/改行組合せ8ケースで保存UTF8から実トークンと呼出辺を確認する。重複1/2threadと無効出力の保持/再試行も別ケースで検証。

**未確定点:** 実GUI、他OS、全入力の原子的取得は検証していない。

**次の作業:** 保存した人工期待・生ログ・有限モデルの負の対照をレビューし、保証を未検証範囲へ拡張しない。

### ANN-007: NoPublicationAfterInvalidOutput

**根拠:** `docs/contracts/formal/PythonOutputValidation.tla`、`NoPublicationAfterInvalidOutput`、manifestのSHA-256と抜粋。契約: EXECUTION-001, LOCATION-001。

**観測:** 正常モデル20 distinct statesを探索。無効出力を無視する変異はNoPublicationAfterInvalidOutputで失敗。

**未確定点:** 有限のDB/ソース2組の検証・公開モデルであり、全スレッド/OS原子性を証明しない。

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
