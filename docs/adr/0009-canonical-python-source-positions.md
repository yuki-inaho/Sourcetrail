# ADR-0009: 旧Python解析器の文字位置を保存内容のUTF-8バイト位置へ変換する

- 状態: 採用。旧Python外部索引器の出力境界
- 日付: 2026-10-31（Asia/Tokyo）
- 関連契約: `LOCATION-001`, `GRAPH-001`, `EXECUTION-001`
- 関連判断: [ADR-0004](0004-language-capabilities.md)、[ADR-0007](0007-external-indexer-outcomes.md)、[ADR-0008](0008-content-based-input-observations.md)

## 背景

旧Python索引器は parso の Unicode スカラー位置から開始列に1を加え、終了列をそのまま保存する。一方、アプリのPython参照後処理は保存した `std::string` のバイト範囲でトークンを取り出す。日本語・補助平面文字を含む行では、数値だけを保存してもトークンと位置の対応を維持できない。

根拠は上流 [shallow_indexer.py の getSourceRangeOfNode](https://github.com/CoatiSoftware/SourcetrailPythonIndexer/blob/master/shallow_indexer.py) と、[TaskExecuteCustomCommands::runPythonPostProcessing](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp) である。実行するバイナリーは既存のハッシュ固定済み `v1_db25_p6` とする。

## 決定

共通保存位置は行・列が1始まり、列単位はUTF-8バイト、終端込みとする。[Utf8SourceLocationMap](../../src/lib_core/Utf8SourceLocationMap.h) は外部依存を持たず、UTF-8の妥当性と文字境界を検証して旧Python列を変換する。

| 入力上の事項 | 保存位置での扱い |
| --- | --- |
| 日本語・補助平面文字 | スカラーの開始境界／終了境界をUTF-8の開始／終了バイトへ写す |
| UTF-8 BOM | 解析器からは見えないが保存内容には残るため、先頭行の列へ3バイトを反映 |
| CRLF・CR | 保存時にLFへ正規化。列計算は保存内容に対して行う |
| スコープ終端の次行・列0 | 直前の保存行の終端へ写す |
| 末尾に改行のない入力 | 解析器の合成終端を実際の最終行へ写す。保存内容の最終改行有無を維持 |
| ゼロ幅診断・スコープ | 境界位置の一点として保存。通常トークンの空範囲は拒否 |
| 不正UTF-8・NUL・範囲外・逆転 | 正常な位置を捏造せず出力拒否 |

[SqliteIndexStorage::normalizePythonSourceLocations](../../src/lib/data/storage/sqlite/SqliteIndexStorage.cpp) は保存内容を取得し、実ファイルとの不一致を検査する。旧DBライブラリーが末尾改行のない入力へ付加する1個のLFだけを許容し、保存内容を実入力の正規化内容へ合わせる。位置行はID・ファイル所属・種別を保ったまま更新し、出現との結合を変えない。一つの処理中に後続ファイルの失敗があれば、savepointで先行更新も戻す。

固定版の旧DBライブラリーは正常な空ファイルの `filecontent` 行を省略する。今回のバイナリー観測を受け、現在入力が実際に空、索引済みPythonの `file` 行が一意に存在し、当該ファイルの位置行が一つもない場合に限り、境界で明示的な空内容の行を作る。保存済みDBの行欠落を未変更とみなす規則ではない。通常の更新判定では欠落のまま再解析対象となり、この出力境界を通って初めて正常な空の観測になる。

変換は全ワーカーの完了後、**DBとソースの組ごとに一度だけ**行う。異なるDBの結果を注入する前に変換し、同じPythonソースを複数コマンドが処理した場合の二重変換を防ぐ。Pythonの名前解決後処理は変換後に行う。PythonとCustomが同一ソースの出力所有を明示している場合は、コマンドを実行する前に拒否する。

## 出力拒否と検証

外部プロセスの終了0と、出力の妥当性を区別する。`ExternalOutputOutcome::InvalidOutput` はプロセスの開始・終了件数を書き換えずに失敗を保持する。`TaskFinishParsing` はその候補を破棄し、採用済み索引を保持してCLIへ終了1を返す。

[人工対象](../../tests/input_observation/test_input_observation.py)は BOM／Unicode／改行の組合せで実トークンを抽出し、呼出辺の向きと種類、同一入力の直列・並列重複を確認する。NULを含む不整合出力と所有衝突で索引保持・修復後再試行を確認する。[SQL試験](../../src/test/InputObservationTestSuite.cpp)はID保持と全選択ファイルのロールバック、[独立コア試験](../../tests/core/utf8_source_location_test.cpp)は手書き位置と異常入力を扱う。

[PythonOutputValidation.tla](../contracts/formal/PythonOutputValidation.tla) はDB／ソース単位の一回変換と失敗後の不採用を有限範囲で検査する。UTF-8変換処理やSQLite実装全体の証明ではない。

## 移行と限界

既に保存されている旧Python索引は、**全体再索引化**して新位置規約へ更新する。既存DBの各行が旧文字列か新バイト列かを推測する自動移行は行わない。UTF-16位置、任意のCustom出力、マクロ展開の位置はこの変換器の入力ではない。新しい解析器が既にUTF-8バイト位置を出す場合、この旧Python専用変換を適用しない。
