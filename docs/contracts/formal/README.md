# 更新計画の有限モデル検査

このディレクトリは、更新対象を選ぶ `REFRESH-001` の集合契約と、その段階的な計算を TLA+ で記述する。
TLC によって**指定した有限範囲内のモデル**を検査する。C++ ソースを自動変換したものではなく、Sourcetrail 全体や任意サイズの入力についての証明ではない。

## 入口

- [抽象契約](RefreshContract.tla): 一度の操作で観測結果を返す仕様。
- [段階的な計画](RefreshPlan.tla): 影響範囲 → 保持するソース → 削除対象 → 索引対象。
- [include/import のモデル設定](RefreshPlan.cfg)。
- [単一の関係を広く調べる設定](RefreshPlanSingleRelation.cfg)。
- [保護条件を外した変異モデル設定](RefreshPlanMutant.cfg): 失敗を期待する検証器の自己確認。
- [実行器](../../../script/verification/check_models.py): 配布物の検証、実行、終了コード・結果判定、証跡の出力。
- [実行器の誤判定防止テスト](../../../tests/contracts/test_models.py)。

## 実行と証跡

リポジトリ直下から次を実行する。

```sh
pixi run -e formal --locked verify-models
```

Java 11 以上と Python 3.9 以上がある環境では、直接実行もできる。再現用の Pixi 環境では Java 17 を固定する。

```sh
python script/verification/check_models.py
python script/verification/check_models.py --offline
```

初回は公式配布の `tla2tools.jar` を `build/formal/` に取得する。`--offline` は取得せず、配布物がなければ失敗する。
別の配置先を使う場合も `--jar /path/to/tla2tools.jar` で**同じ SHA-256 の配布物**を指定する。存在するキャッシュのハッシュが違う場合は、そのファイルを実行せず失敗する。

実行器は次を出力する。

| ファイル | 内容 |
| --- | --- |
| `build/formal/summary.json` | 結果、状態数、モデル・設定ファイルの SHA-256、配布元・ツールの SHA-256、Java バージョン、実行引数、所要時間 |
| `build/formal/refresh-mixed.log` | include/import の有限モデル検査 |
| `build/formal/refresh-single-relation.log` | 単一の関係の有限モデル検査 |
| `build/formal/refresh-negative-control.log` | 意図した共有依存の消去を示す反例 |

通常モデルの終了コード 0 だけでは合格としない。検査完了の表示、非ゼロの探索状態数、未処理状態が 0 であることも確認する。
変異モデルは TLC の不変条件違反の終了コード `12`、`SharedDependenciesPreserved` の違反、反例の表示を要求する。
構文エラー、Java の起動失敗、タイムアウト、別の不変条件の違反は、変異モデルでも合格にならない。
各設定の制限時間は既定で 300 秒。全体の実行器は一つでも期待と違えば非ゼロで終了する。

## 対象とするソフトウェア境界

[RefreshPlan::forUpdatedFiles](../../../src/lib/project/RefreshPlan.cpp) は、分類済みの集合と読み取り専用の依存関係問い合わせを受け取り、`filesToClear` と `filesToIndex` を返す。
[RefreshInfoGenerator](../../../src/lib/project/RefreshInfoGenerator.cpp) がファイルシステム・DB・有効なソースグループを調べ、その入力を組み立てる。

| モデル | 実装・前提 |
| --- | --- |
| `Files` | 今回扱う有限のファイル識別子。パス文字列・大小文字・シンボリックリンクは抽象化する |
| `sources` | 有効なソースグループが現在索引化でき、存在するソースファイルの集合 |
| `unchanged` | 変更なし、かつ索引化済みと分類されたファイル |
| `changed` | 変更・削除などによって消去候補になった既知のファイル |
| `includeEdges` | include に基づくファイル間の関係 |
| `importEdges` | import に基づくファイル間の関係 |
| `clear`, `index` | 計画完了後に呼び出し元が観測する二つの集合 |

分類の前提は `unchanged ∩ changed = ∅`。分類そのものの正しさはこのモデルの対象外。
二つの問い合わせは同じ固定スナップショットを参照し、集合を返し、副作用を持たないものとする。
ファイルの消去、解析器の実行、DB 更新、実際に新しい索引が作られることはモデル化していない。

### 依存関係の意味

[PersistentStorage::getReferenced / getReferencing](../../../src/lib/data/storage/PersistentStorage.cpp) は、include の推移閉包と import の推移閉包を**別々に計算してから和集合にする**。
モデルもこの振る舞いを維持する。例えば `a --include--> b --import--> c` だけがあるとき、`Referenced({a})` に `c` は入らない。
二つの辺種を混ぜて一つの推移閉包を作る変更は、このリファクタリングの範囲外であり、別の契約変更として扱う。

到達可能性は長さ 1 以上の経路で定義する。循環があると起点自身が戻る場合がある。
`Reach` はファイル数を上限にたどる。有限グラフでは、到達先への単純経路、または起点に戻る単純な循環で十分なため、この長さで集合が得られる。

## 契約と段階的計算

`S` を `sources`、`U` を `unchanged`、`D` を `changed` とする。
`R(X)` は X が参照するファイル、`R⁻¹(X)` は X を参照するファイルで、前節の二種類の閉包の和集合である。

```text
A = D ∪ R⁻¹(D)                       変更箇所と、その参照元
K = S − A                            今回は保持するソース
C = A ∪ (R(A) − (R(K) ∪ K))          消去するファイル
I = {f ∈ S | f ∈ C または f ∉ U}     索引化するソース
```

抽象契約は各ファイルが条件を満たすかを述べる。段階的なモデルは `A`、`K`、`C`、`I` を順番に計算する。
呼び出し元には完了後の結果だけを見せる `Reference` 写像により、途中の計算は抽象契約の値が変わらないステップとして扱う。
これが、このモデルで使う refinement（詳細化）の意味である。

共有依存の保護には例外がある。`A` に含まれるファイルは、保持するソースからも参照されていても消去対象である。
「共有されるファイルは一切消さない」という契約ではない。保護対象は `R(A)` から**追加**しようとするファイルのうち、`K` または `R(K)` にあるもの。

## 検査項目

| 識別子 | 内容 |
| --- | --- |
| `TypeInvariant` | 入出力、途中の集合、段階の型と範囲が保たれる |
| `ResultMatchesContract` | 完了時の二つの集合が、抽象契約の期待集合と等しい |
| `SharedDependenciesPreserved` | 保持するソースとその依存を、依存清掃のために追加消去しない |
| `ChangedFilesIncluded` | 変更・削除と分類されたファイルを消去対象から落とさない |
| `IndexSelectionComplete` | クリアされるソースと新規・変更ソースを選び、範囲外のファイルを索引対象にしない |
| `Refinement` | 途中の計算を隠した状態列が、抽象契約の許す状態列である |

完了するまでの段階の数は有限だが、仕様は状態が変わらないステップも許す。公平性を仮定していないため、処理が必ずいつか完了するという liveness の主張はしない。
TLC のデッドロック検査は無効化していない。完了状態には明示的な状態不変の遷移を置く。

## 検証範囲と初回実測

2026-10-30 に TLC 1.7.4 / Java 17 で実行。

| 設定 | 有限範囲 | 初期状態 | 異なる探索状態 | 生成状態 | 結果 |
| --- | --- | ---: | ---: | ---: | --- |
| `RefreshPlan.cfg` | 3 ファイル、各関係に非自己辺 0〜2 本、全ソース集合、互いに素な変更・不変集合 | 104,544 | 522,720 | 627,264 | 不変条件・詳細化の違反なし |
| `RefreshPlanSingleRelation.cfg` | 3 ファイル、include の非自己辺 6 候補の全 64 グラフ、import なし、同じ分類範囲 | 13,824 | 69,120 | 82,944 | 不変条件・詳細化の違反なし |
| `RefreshPlanMutant.cfg` | 2 ソースが 1 依存を共有し、片方だけ変更。共有依存の保護を無効化 | 6 | 実行ログを参照 | 実行ログを参照 | 共有依存の消去を反例として検出 |

両通常設定とも探索深度は 5。最初の設定には二種類の辺が混在するケースと 2 ファイルの循環が含まれる。
二番目には 3 ファイルの循環も含まれる。自己辺は TLA+ の列挙範囲に含めず、C++ 側の独立した例で確認する。
これらの件数はモデル変更後に自動で維持される定数ではない。変更時は新しい `summary.json` から再計算し、差分をレビューする。

TLC は状態の指紋値を使って探索するため、通常モデルの実行ログには衝突確率の推定も出る。任意サイズに対する数学的証明や C++ との機械的な対応証明を得るには、別途証明と実装対応の検証が必要になる。

## 実装との対応と、まだ検証しない範囲

[RefreshPlanTestSuite.cpp](../../../src/test/RefreshPlanTestSuite.cpp) は実際の C++ の計画関数を実行し、独立した到達可能性計算とファイルごとの条件を使う期待値に比較する。
有限モデル検査とこの実装テストは別の検証単位であり、両方が成功したことを根拠として記録する。TLA+ だけの成功を C++ の成功へ読み替えない。

次は対象外として残す。

- 更新時刻・内容比較による変更検出。更新時刻が進まない変更の扱い。
- 不完全な索引の再実行モード、ソースグループの有効・無効の変更、パス解決。
- ストレージの include/import 関係抽出の正しさ、削除のトランザクション、索引ファイルの公開・クラッシュ回復。
- 並列ワーカー、途中キャンセル、解析器の異常終了、キュー配送。
- 言語構文の認識、名前解決、Rust の新しい概念、GUI の観測結果。

新たな境界を形式化するときは、この一覧から対象を選び、先に抽象状態・観測結果・実装との対応・有限範囲・反例を決める。未実装の目標モデルは、現行実装の保証と混在させない。

## ツールの固定と一次資料

| 項目 | 固定値 |
| --- | --- |
| 配布物 | `tla2tools.jar` / release `v1.7.4` |
| SHA-256 | `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` |
| 公式リリースの SHA-1 との照合 | `bee4a54f3ee3d4afc347c3240ec2d9e93b075104` |
| TLC の表示バージョン | `2.19 of 08 August 2024 (rev: 5a47802)` |
| ワーカー数 / 指紋多項式 / seed | `1` / `0` / `1` |

SHA-256 は公式配布物を取得して計算し、公式リリースが公開する SHA-1 とも一致を確認した。これは配布物の署名検証という意味ではない。
現在の upstream の `v1.8.0` は継続更新される prerelease と説明されているため、この検証には固定した安定版を使う。

- [公式 v1.7.4 リリース](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4)。
- [公式ツールの使い方](https://github.com/tlaplus/tlaplus/blob/master/USE.md)。
- [TLA+ 公式リポジトリと prerelease の説明](https://github.com/tlaplus/tlaplus)。
- [Leslie Lamport: Stuttering Steps](https://lamport.azurewebsites.net/tla/stuttering.html)。
- [Leslie Lamport: Safety, Liveness, and Fairness](https://lamport.azurewebsites.net/tla/safety-liveness.pdf)。

資料の確認日: 2026-10-30。ツール更新時は配布物・Java・モデル結果・負の対照をまとめて再検証する。
