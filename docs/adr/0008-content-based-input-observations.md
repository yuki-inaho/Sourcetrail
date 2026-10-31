# ADR-0008: 入力の変更判定を内容観測として分離する

- 状態: 採用
- 日付: 2026-10-31（Asia/Tokyo）
- 関連契約: `INPUT-001`, `REFRESH-001`, `GRAPH-001`
- 関連判断: [ADR-0002](0002-pure-refresh-planning.md)、[ADR-0006](0006-portable-refresh-core.md)

## 背景と再実装の根拠

この文書と実装は、[中断時の引継ぎ](../handoffs/input-observation-checkpoint-2026-10-31.md)を受けて再実装したものである。未公開コミットの原ファイルを回収したという意味ではない。過去の試験件数を今回の成功証跡に用いない。

旧 `RefreshInfoGenerator::didFileChange` は更新時刻が進んだ場合だけ内容を比較した。同一時刻の置換、過去時刻への復元を見落とし、`hasContentForFile` は正常な空文字列と保存行の欠落を同一視した。さらに取得失敗を空文字列へ置き換える API と表示用のディスクへの補完を変更判定にも使っていた。

## 決定

[SourceChange.h](../../src/lib_core/SourceChange.h) は、保存内容と現在内容の観測、索引対象かどうか、更新時刻の比較結果だけを受け取る標準C++の値処理とする。ファイル、SQLite、Qt、Boost、依存グラフはこの型へ持ち込まない。

| 観測 | 意味 | 判定 |
| --- | --- | --- |
| 両方取得済み、内容同一 | 正常な空文字列も含む | 時刻に関係なく変更なし |
| 両方取得済み、内容不一致 | 同一時刻・時刻逆行も含む | 再索引化 |
| 現在の読込失敗 | 内容を観測できない | 保守的な再索引化 |
| 索引済み入力の保存行欠落・NULL・SQL失敗 | 正常な空内容ではない | 保守的な再索引化 |
| 非索引依存の保存行欠落 | 従来から内容を保存しない依存 | 更新時刻による弱い互換判定 |

`TextAccess::tryCreateFromFile` は失敗を null ポインターで返し、正常な空ファイルは非nullとして返す。表示用 `createFromFile` の空内容への補完は残すが、変更判定はその API を使わない。読込内容は既存の保存・表示規約に沿って改行をLFへ正規化し、最終改行の有無は保持する。

`SqliteIndexStorage::tryGetStoredFileContentByPath` は引数を束縛した問い合わせを使い、保存行欠落、SQL NULL、取得失敗を別の状態で返す。取得は長さ付きで行い、埋込NULによる切詰めを成功した観測として扱わない。`PersistentStorage` の表示経路も、取得済みの空文字列を現在ディスク内容へ置き換えない。

最終改行の保持で、XMLの終端に改行がない既存設定もそのまま読み込むようになる。`ConfigManager::load` は TinyXML の返り値のポインターではなく `doc.Error()` で成否を判定する。正常に終端まで解析した場合にも返り値がnullとなる既存ライブラリーの規約に合わせる補修であり、設定・プロジェクトXMLへ改行を強制するものではない。引用符を含むファイル名の初期登録に使う `getFileByPath` の問い合わせも束縛変数へ変更する。

## 検証単位

[入力観測の人工対象](../../tests/input_observation/README.md)は、同一mtime、過去mtime、内容不変のtouch、空への切詰め、空からの追加、保存行欠落・NULL、最終改行の除去を C++／Python の実CLIで行う。必要な定義、保存内容、再実行件数と、更新後／全体再構築の意味比較を別々に確認する。

[値処理の試験](../../tests/core/source_change_test.cpp)、[SQLite・読込の試験](../../src/test/InputObservationTestSuite.cpp)、[更新計画との接続](../../src/test/RefreshInfoGeneratorTestSuite.cpp)を分ける。[有限モデル](../contracts/formal/SourceObservation.tla)では内容差・時刻・欠落状態の組合せを検査し、mtimeで内容比較を遮断する変異版で `ContentChangesDetected` の反例を要求する。

既存の更新計画試験は、ファイル作成前の読込失敗を未来mtimeで隠していた箇所を、保存内容が実在する入力へ修正する。変更対象の期待集合を弱める変更ではない。

## 限界

LFとCRLFの差だけは表示・保存の正規化により同じ内容として扱う。ファイルの原子的取得や、全入力を同じ時点で固定する保証は追加していない。読込失敗を再索引化へ回すことは、その後の解析成功を保証しない。非索引依存で内容を保存しない経路の同一mtime問題は、能力の制約として残る。
