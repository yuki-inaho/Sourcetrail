# 012 新版Python・C++・Rustの実装と統合

## 対象・入力版・実施したこと

2026-10-31（Asia/Tokyo）、source 10単位。基準 `4d69a44ac67d03e4117c266d491c01a7a4ba87f7` からのworking-treeを対象とする。公開されていた前回ブランチで継続し、未回収の実装を回収したとはせず、GAP-002/003を再実装した上で新版3言語を接続した。

Python 3.14.10、Clang 18.1.8、Rust 1.85.1／rust-analyzer 0.3.2328を固定した別環境を追加した。旧Python／Clang11の経路を残し、Modern Language Source Groupを設定型として追加した。GUIの設定画面へ表示・編集経路を接続したが、実GUI操作の自動化を完了したとはしない。

利用手順と機能範囲は[新版解析器](../../../architecture/modern-indexers.md)、判断は[ADR-0011](../../../adr/0011-modern-language-adapters.md)・[0012](../../../adr/0012-modern-cpp-indexer.md)・[0013](../../../adr/0013-rust-source-indexer.md)。入力・旧Python位置の再実装は[010](../010-input-observation-contracts/report.md)と[011](../011-source-position-contracts/report.md)に分けた。

## 注釈

### ANN-001: def index_project(

**根拠:** `script/indexers/python_indexer.py`。SHA-256と抜粋はmanifest。契約: LANGUAGE-001, NAME-001, RELATION-001。

**観測:** CPython3.14のASTと静的コンパイル検査を使い、スコープ・import・確定できる呼出・新構文を共通グラフへ写す。再代入や局所スコープによる誤った呼出辺は独立レビューの反例で修正した。

**未確定点:** 動的実行・一般型推論・旧Jedi全能力の等価性は宣言しない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-002: def index_project(

**根拠:** `script/indexers/cpp_indexer.py`。SHA-256と抜粋はmanifest。契約: LANGUAGE-001, NAME-001, RELATION-001。

**観測:** Clang18.1.8のC索引APIで宣言・参照通知を取得し、export内部、制約付きtemplate、overload、coroutine、BMIを使うmodulesを扱う。CDBの引数と作業ディレクトリを保持する。

**未確定点:** BMI自動生成やC++20/23規格全体への適合ではない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-003: def index_project(

**根拠:** `script/indexers/rust_indexer.py`。SHA-256と抜粋はmanifest。契約: LANGUAGE-001, NAME-001, RELATION-001。

**観測:** 固定rust-analyzerの意味問い合わせとCargo診断を使い、crate・構成・trait/impl・呼出・位置を保存する。全監視入力と有効crateの意味対象を分ける。

**未確定点:** build.rs/proc-macro依存、カスタムJSON target、依存ソース全体の取り込みは対応範囲外。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-004: class RustLanguageServer:

**根拠:** `script/indexers/rust_lsp.py`。SHA-256と抜粋はmanifest。契約: EXECUTION-001, LANGUAGE-001。

**観測:** UTF-8位置を交渉し、要求ID・フレーミング・能力を検査する。stdout/stderrを並行排出し、期限超過やプロトコル失敗では実プロセスを回収する。

**未確定点:** 任意CustomやGUI取消全体の子プロセス制御を置き換えない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-005: def write_graph(

**根拠:** `script/indexers/graph.py`。SHA-256と抜粋はmanifest。契約: STORAGE-001, NAME-001, LOCATION-001。

**観測:** 名前・参照・位置・DB版と構造を検査し、LF保存規約へ写した内容を一つのSQLトランザクションで注入する。後続注入の衝突も拒否する。

**未確定点:** DBファイル公開のクラッシュ原子性や全入力の原子的取得とは別。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-006: def configure_project(

**根拠:** `script/indexers/cli.py`。SHA-256と抜粋はmanifest。契約: COMMAND-001, LANGUAGE-001, INPUT-001。

**観測:** 版付き設定とModernグループを生成し、エンジン能力・入力内容の再照合を保存前に行う。ソースと設定を更新検出の入力に接続する。

**未確定点:** 任意の実行環境移動に自動追従しない。明示した実行ファイルパスの更新が必要。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-007: SourceGroupCustomCommand::getIndexerCommands(

**根拠:** `src/lib/project/SourceGroupCustomCommand.cpp`。SHA-256と抜粋はmanifest。契約: SOURCE-GROUP-001, COMMAND-001。

**観測:** Modernグループを全体解析一回のコマンドへまとめ、明示した設定ファイルも入力として列挙する。部分消去は許可しない。

**未確定点:** GUIの実操作を検証したという意味ではない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-008: bool incompatiblePythonOwnership = false;

**根拠:** `src/lib/project/Project.cpp`。SHA-256と抜粋はmanifest。契約: SOURCE-GROUP-001, EXECUTION-001, LOCATION-001。

**観測:** Modernを外部実行providerへ送り、旧Pythonとの所有集合重複を実行前に拒否する。代表コマンドのパスだけで重複を判断しない。

**未確定点:** 一般的な全言語/全構成の重複統合規則を確立したものではない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-009: def test_real_app_refresh_delete_empty_and_clean_equivalence(

**根拠:** `tests/modern_indexers/test_app_e2e.py`。SHA-256と抜粋はmanifest。契約: GRAPH-001, REFRESH-001, EXECUTION-001。

**観測:** 実アプリで無変更・編集・削除・空化・全体再構築との一致、版不一致の既存索引保持と再試行を確認する。旧/Modern混在も1/2ワーカーで観測する。

**未確定点:** Linux CLIの人工対象であり実GUI・他OS・大規模性能を保証しない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

### ANN-010: [feature.modern.dependencies]

**根拠:** `pixi.toml`。SHA-256と抜粋はmanifest。契約: LANGUAGE-001, VERIFICATION-001。

**観測:** 旧解析環境を維持してModern環境を追加し、最終verifyへ新しい解析器の実エンジン試験を接続する。依存の解決結果はpixi.lockへ固定する。

**未確定点:** 将来の最新版の追随や他OSへの配布完了を意味しない。

**次の作業:** 最終verifyと公開版CIを同じソースへ照合し、記録した能力境界を維持する。

## 検証記録

`pixi run --locked verify` は終了コード0で完了した。[全体ログ](evidence/full-verify.txt)にCTest15群、文書、有限モデル9設定、可搬コア、新版205件の成功を保存した。レビュー終端に追加した共有namespace/moduleの2ケースも含め、実装と試験を固定して新版全体を再実行し、**207件成功、失敗・エラー・skipは0**だった。開始時と終了時の全15実装/試験ファイルのSHA-256一致も確認した。

| ゲート | 実際の結果 | 公開証跡 |
| --- | --- | --- |
| `pixi run --locked verify` | 終了コード0 | [全体ログ](evidence/full-verify.txt) |
| ネイティブCTest | 15群すべて成功。旧回帰、人工対象、入力/位置28件、外部失敗31件、検証器125件等を含む | [JUnit](evidence/ctest-results.xml) |
| 依存のないコアの別ビルド | 5群すべて成功 | [JUnit](evidence/core-results.xml) |
| 有限モデル | 5正常設定と4つの指定反例が期待どおり。未処理0は正常設定で確認 | [要約](evidence/formal-summary.json)と同ディレクトリの生ログ |
| 可搬コアの共通期待 | C++とRust参照実装を各32,778ベクトルで比較、不一致0。負の対照を検出 | [結果](evidence/portability-summary.json) |
| 最終新版解析器 | 207件成功。3言語の実エンジン・保存・設定・実アプリ15件を含む | [生ログ](evidence/final-modern-tests.txt)、[JUnit](evidence/final-modern-results.xml) |
| ソースの固定 | 最終新版再実行の前後で全15ファイル一致 | [SHA-256](evidence/final-source-snapshot.json) |

文書は45 Markdown・20契約・6言語プロファイル・12レポートを検査しエラー0だった。無視されたbuild成果物を含めないGit indexの書き出しでも同じ検査が成功した。[作業ツリー](evidence/docs-worktree-check.json)、[Git index書き出し](evidence/docs-export-check.json)。

ケース数、assertions、有限モデルの状態数、参照移植のベクトル数を合算しない。Rustの参照移植は更新ポリシーの比較であり、Rustソース索引器の受入とは別である。詳細の実行コマンド、判定、モジュール別件数は[verification.json](evidence/verification.json)。CIでの最終受入は公開PRとそのheadに対応する実行結果から確認する。

## 発見・修正と保証の境界

Pythonでは再代入・lambda・例外変数・注釈・global/nonlocal・静的構文検査の反例を修正した。C++では制約の異なるtemplateがClangの同じUSRを持つ実例を識別し、export内部をcursor木だけで見落とさないC索引APIを採用した。Rustでは標準ライブラリーの依存準備、内部Cargoのlock固定、cfg/test/targetの一致、未選択入力の監視を修正した。

共通保存では複数回注入の名前/種別衝突、complete/indexedの集約、DBの主キー/外部キー、CRLF診断位置を検査した。アプリ統合ではModernが内部IPCへ誤配送され空の成功となる経路を修正し、旧/Modernが同一Pythonソースを共有する設定を全ソース集合の交差で拒否した。試験用HOMEはSourcetrailが配置するサンプルを解析対象へ混入させないようソース外に置く。

構文診断による不完全なグラフと、プロトコル・位置・所有・入力競合による拒否を区別する。旧Pythonの保存DBは全体再索引化が必要。一般Customのタイムアウト/取消、DB公開のクラッシュ耐性、全入力の原子的取得、GUIナビゲーション、他OS、任意規模での性能はこのPRで完了したとはしない。

## 次の作業と受入条件

最終verifyの成功を保持し、追跡対象だけの文書検査と公開ツリーの一致を確認する。公開版のCIとPR headを照合してからmasterへマージする。後続能力の追加は、明示した構成・独立した期待・実エンジン・実アプリの観測を揃えて別のプロファイルとしてレビューする。

## レビュー状態

担当を分けたソース・実例レビューを実施。旧Python担当による自己実装の確認は独立実装レビューとはせず、報告書の第二読解として区別する。[資料の最終照合](evidence/final-report-review.json)でも重大誤記0・残証跡欠落0を確認した。ユーザー側レビューと実GUI操作は未実施。
