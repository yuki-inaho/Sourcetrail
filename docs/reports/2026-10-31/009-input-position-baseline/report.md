# 009 入力・位置の公開基準の再構成

## 対象・入力版・実施したこと

2026-10-31（Asia/Tokyo）、source 3単位。公開ブランチ `refactor/input-observation-contracts` の基準コミット `4d69a44ac67d03e4117c266d491c01a7a4ba87f7` を `git show` で読んだ。

**このバッチは新しい再構成記録である。前回の009〜011の元ファイルを回収したものではない。** 前回記録の未公開コミットと実装本体は回収できなかった。公開済みの引継ぎ、依頼で保持された要件、実コードを入力として再実装し、その検証を010・011・012へ記録する。過去の実行成功件数や失われたハッシュを推測で補わない。

基準版のバイナリーを再ビルドして実験したとは扱わない。このバッチの根拠は公開ソースの読解であり、現在の人工対象から独立した期待を作るための出発点である。

## 注釈

### ANN-001: bool RefreshInfoGenerator::didFileChange(

**根拠:** `src/lib/project/RefreshInfoGenerator.cpp`、`bool RefreshInfoGenerator::didFileChange(`。SHA-256と原文抜粋はmanifestに固定。契約: INPUT-001, REFRESH-001。

**観測:** 内容比較はmtimeが保存値より新しい場合にしか実行されない。同時刻・過去の変更を見落とす経路が基準コミットに残る。

**未確定点:** 変更の実アプリ再現はこの基準読解では実施せず、再実装後の独立期待との照合を010へ記録する。

**次の作業:** レポート010・011の再実装、独立した人工期待、実行証跡をレビューする。

### ANN-002: std::vector<std::string> TextAccess::readFile(

**根拠:** `src/lib/utility/text/TextAccess.cpp`、`std::vector<std::string> TextAccess::readFile(`。SHA-256と原文抜粋はmanifestに固定。契約: INPUT-001。

**観測:** 読込失敗は空vectorとなり、createFromFileは常にTextAccessを返す。正常な空と失敗を返却型で区別できない。行読込時に改行を付加する。

**未確定点:** 新しいchecked読込の導入は既存呼出元へ影響するため、設定読込と既存5試験群の再確認が必要。

**次の作業:** レポート010・011の再実装、独立した人工期待、実行証跡をレビューする。

### ANN-003: void TaskExecuteCustomCommands::runPythonPostProcessing(

**根拠:** `src/lib/data/indexer/TaskExecuteCustomCommands.cpp`、`void TaskExecuteCustomCommands::runPythonPostProcessing(`。SHA-256と原文抜粋はmanifestに固定。契約: LOCATION-001, EXECUTION-001。

**観測:** 後処理は保存された列をstd::stringのバイト添字として使う。基準版には旧Pythonの文字列位置をUTF-8バイトへ変換する検査段階がない。

**未確定点:** 変換・不正出力拒否は011の新実装と実エンジン観測で評価する。一般Custom出力全体の意味検査とは区別する。

**次の作業:** レポート010・011の再実装、独立した人工期待、実行証跡をレビューする。

## 検証記録

| 操作 | 結果 | 根拠 |
| --- | --- | --- |
| 公開ブランチの基準取得と対象3ファイルの読解 | 成功。取得した全文とSHA-256を保存 | [回収境界](evidence/recovery.json)、`baseline-01.txt`〜`baseline-03.txt` |
| 旧非公開実装・元レポート一式の回収 | 未達。新実装へ置き換えて検証 | [公開引継ぎ](../../../handoffs/input-observation-checkpoint-2026-10-31.md) |
| 基準バイナリーでの再現試験 | このバッチでは未実施 | 成功扱いしない |

## 次の作業と受入条件

010では同一・過去mtime、空・保存欠落・読込失敗を分離し、更新後の意味グラフを全体再構築に照合する。011では保存UTF-8から実トークンを照合し、異常出力の旧索引保持と再試行を実アプリで確認する。012では新版Python/C++/Rustを実アプリへ接続し、実エンジン・更新・保存境界を確認する。

## レビュー状態

assistantによる公開基準の読解を実施。ユーザー側のレビューは未実施。実GUI・画像注釈・他OSの試験を行ったとは記録しない。
