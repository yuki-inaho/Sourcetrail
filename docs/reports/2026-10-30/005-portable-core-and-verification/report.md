# 005 — 可搬コアへの再構成と同等性の検証

作業日: 2026-10-30（UTC）。基準: `993ab43eba5b3055a409a73f686021233a687523` からの作業ツリー。
本バッチは [004の人工対象と旧基準](../004-toy-project-design-and-baseline/report.md) を使い、意図した不具合修正と同等な構造変更を分離して確認する。

## 変更の目的と構成

標準ライブラリーだけを使う値処理と、パス・設定・DB・Qt・外部プロセスに接続する処理を分けた。
設計判断は [ADR-0006](../../../adr/0006-portable-refresh-core.md)、人工対象の設計は [ADR-0005](../../../adr/0005-toy-project-conformance.md) に記す。
言語の対応能力や保存形式はこの構造変更で増やさず、現在の入力が持つ意味を比較の基準とする。

| 観点 | 実施した整理 | 確認する境界 |
| --- | --- | --- |
| 単一責務 | 更新集合の計算と依存の問い合わせを分ける | コアにFilePath・DB・Qtを渡さない |
| 依存の向き | 既存アダプターが標準C++コアを呼ぶ | アダプターの問い合わせ順、既存のAPI・呼び出し元を保持 |
| 重複の削減 | Python／Customの選択・文脈・コマンド構築を共通化 | 種別、並列指定、順序、空の選択を保持 |
| 単純さ | 小さい値型と関数、薄い既存型アダプター | 汎用プラグイン層や公開ABIを新設しない |
| 移植可能な単位 | 不透明な識別子集合と文字列の変数展開 | 独立ビルド、C++／Rust／独立オラクルの比較 |

SOLIDの各語を満たしたという包括的な認証ではなく、上記の変更と試験で確認できる責務・依存関係を評価する。

## 注釈単位

### ANN-001 — 値だけの更新計画

`src/lib_core/RefreshPlanner.h` は `prepareUpdatedRefresh` と `finishUpdatedRefresh` を提供する。
Keyは順序付き集合の識別子で、ファイルを開かず、パスを正規化せず、`operator==` を要求しない。
整数識別子と等値演算を持たない型で試験し、独立したコアビルドにも含める。REFRESH-001、REFRESH-002、PORTABILITY-001 に対応する。

### ANN-002 — 既存APIを残すアダプター

`src/lib/project/RefreshPlan.cpp` は、依存元、保持するソースの依存先、当初の消去集合の依存先、という問い合わせ順を維持する。
includeとimportの閉包を別々に計算する保存層の意味も維持する。コアは取得済み集合を受け取り、スナップショット同期を自動で保証するとは扱わない。

### ANN-003 — 外部コマンドの値処理

`src/lib_core/IndexerCommandTemplate.h` は、PROJECT → DATABASE → VERSION → SOURCE の順に既知変数を展開する。
後の変数を値が導入した場合はその後の段階で展開し、同じ変数や以前の変数へは戻らない。不明変数と引数境界を保持する。
UTF-8文字列と既存のwide文字列を別に試験する。wide文字列をそのままRustのABIに使う設計ではない。COMMAND-001 に対応する。

### ANN-004 — Python／Customの共通構築

`src/lib/data/indexer/ExternalIndexerCommandBuilder.cpp` が、所有ソースと索引対象の積集合を既存の順序で選び、プロジェクト・DBの文脈を組み立てる。
空の選択ではProjectSettingsを参照しない既存の挙動を保持する。言語固有のフラグと実際のプロセス起動は各アダプターに残る。
`IndexerCommandCustom` の生テンプレートの直列化と実行時DB差し替えも維持する。

### ANN-005 — 意図した保存層の修正

`SqliteIndexStorage::removeElementsWithLocationInFiles` は、消去する全ファイルの外に両端の出現が残るMEMBER辺を保持する。
旧トイで失われた3本の所属辺を回復し、削除された子は残さない。MEMBER以外や、辺自身が消去対象に出現する場合の先行消去は従来どおり。
これは STORAGE-002 による振る舞いの修正であり、等価なリファクタリングとは分ける。

### ANN-006 — 別言語へ移す単位の検証

`script/verification/check_portability.py` は、実際のC++更新コアと標準ライブラリーだけのRust参照実装へ同じ値入力を渡す。
`refresh-sets-v1` は6入力集合・4出力集合のテスト用形式で、64ビットは搬送形式の範囲である。本番コアのファイル数上限や公開ABIではない。
十個の手書き期待値と32,768個の独立Boolean／Warshallオラクル入力を比較する。共有依存保護を欠く変異版が、指定の反例で不一致になることも要求する。

### ANN-007 — トイ比較器の失敗を確実に残す

`tests/toy_projects/runner.py` は必要な事実、全体比較、入力・期待値・スナップショットのハッシュを併用する。
独立レビューで、不正な `languages: []` が例外になった際に古い成功レポートが残る問題を発見した。
構造を明示的に拒否し、基準結果の上書き保護を通過した直後に失敗状態を保存する。予期しない例外でも過去の成功状態は残さない。
新しい実行器は自身と意味比較器のハッシュも保存する。既存の基準記録へ過去のハッシュを遡って補わない。

### ANN-008 — 実行ゲート

`cmake/testing.cmake` は実アプリケーションを必要とするトイ試験をC++／Python両パッケージが有効な場合だけ登録する。
`pixi verify` はアプリ、コア、文書、形式モデル、Rust適合を実行する。

### ANN-009 — コンパイル境界

`Sourcetrail_core` はアプリのlibへPRIVATE接続し、LLVM11解析器のGNU C++14へC++17要求を伝播させない。
独立レビューと最終実行の記録で、生成されたcompile_commandsの双方を確認した。

## 三段階の比較

1. 元の本番コードに対応すると申告した既存ビルドで全14段階を観測し、C++削除段階の失敗を保存した。
2. 8個の構造変更ファイルを退避し、本番の変更を保存層の限定修正だけにして再ビルドした。
3. 同じ入力で修正のみの成功基準を保存した後、構造変更を戻して再ビルドし、全14スナップショットを比較した。

修正のみの [ビルド入力](evidence/baseline-corrected/build-inputs.json) と [パッチ](evidence/baseline-corrected/correction-only.patch)、
[結果](evidence/baseline-corrected/summary.json)、[意図した差の検査](evidence/baseline-corrected/intentional-delta.json) を保存する。
元の実装からの意味の差は、C++の削除段階に追加された3本のMEMBER辺だけで、13段階と他の観測項目は一致した。
修正のみの基準から構造変更後へは、両言語の全14段階が一致した。

## 最終の統合実行結果

```sh
SOURCETRAIL_TOY_BASELINE=/absolute/path/to/build/toy-projects/baseline-corrected/summary.json \
  pixi run --locked verify
```

終了コードは **0**。全10 CTestスイートが成功し、選択外・skipはない。
[実出力](evidence/verify.log)、[JUnit](evidence/ctest-results.xml)、[件数・ソースハッシュ・ビルド設定](evidence/verification.json) を保存した。

| CTestスイート | ケース・検査 | 結果 |
| --- | ---: | --- |
| legacy | 608ケース／1,616 assertions | 成功 |
| cpp-contracts | 22ケース／65,669 assertions | 成功 |
| verification-contracts | 119 pytestケース | 成功 |
| cpp-regression | 7ケース／54 assertions | 成功 |
| cpp-e2e | 3ケース／270 assertions | 成功 |
| python-regression | 4 pytestケース | 成功 |
| python-e2e | 4 pytestケース | 成功 |
| toy-projects | 30 pytestケース、14観測の新旧比較 | 成功 |
| core-refresh-contracts | 独立例、等値演算なしの型、32,768有限入力 | 成功 |
| core-command-contracts | 5つの独立した文字列・引数シナリオ | 成功 |

Catchとpytestは合計 **797ケース**。最後の2行は単独C++プログラムとして数え、有限入力数をケース総数へ混ぜない。
トイは両言語7段階ずつの必要な事実、実行内8比較、修正済み基準との14比較が成功した。
[最終観測](evidence/refactored/summary.json) に実行ファイル・実行器・入力のハッシュを含める。

TLCは混合関係モデルの522,720状態、単一関係モデルの69,120状態を検査し、保護を外した変異版は指定した共有依存の不変条件に違反した。
[形式モデルの結果](evidence/formal-summary.json) は有限範囲と終了状態を記録する。全プログラムや任意入力サイズの証明ではない。

独立したportability環境でも [2コア試験](evidence/standalone-core-results.xml) が成功した。
GCC 12.4.0のC++本番コアとRust 1.85.1の参照移植は、それぞれ **10手書き例＋32,768有限例＝32,778入力**で独立期待値と一致した。
両出力のSHA-256は `c18ff1dd414a61ad212f3cf75a7beb96f767c49c7c57e38f5337528a4f8b32d2`。
変異版では `shared-and-private` と `protect-static-source` の不一致を検出した。
[版・ソース・実行結果](evidence/portability-summary.json) と [実際の出力列](evidence/portability/) を保存する。

## 独立レビューと実行上の問題

[コマンド境界のレビュー](evidence/external-command-review.json) と [統合レビュー](evidence/integration-review.json) はassistant側の別担当が実施した。
空の選択時のProjectSettings参照と、不正基準の後に古い成功レポートが残る問題を指摘し、修正と再確認を記録した。
ソースのフィンガープリントは各読解時点の値であり、後のinclude整理などで変わったものを過去のハッシュに上書きしない。
ユーザー側ローカルエージェントのレビューは未実施で、状態をpendingにする。

最初の統合実行は、生成されたCatch実行ファイルが0644で、4スイートを起動できなかった。
[失敗ログ](evidence/initial-verify-failed.log) を保持し、[生成物の再リンク](evidence/test-relink.log) で0755になったことを確認した。
[再リンク記録](evidence/test-executable-relink.json) は前後のモードとハッシュを残す。起動できなかったテストを成功扱いにしない。
再リンク前後で実行ファイルのバイト列のSHA-256は同一だった。権限が変わった原因は特定しておらず、今回確認したのは生成物の再作成による復旧と、その後の全ゲートの成功である。

## 残る範囲と次の受入条件

| 範囲 | 現在の境界 | 次の入力・受入条件 |
| --- | --- | --- |
| 新しいPython／C++構文 | 既存解析器と固定能力のまま | 新解析器の版・能力を宣言し、共通範囲と新構文を別々に検査 |
| Rustソース解析 | 更新コアの参照移植を検査した段階 | Cargo、edition、trait/impl、マクロ位置の仕様と専用トイ、共通探索操作の適合試験 |
| 保存・消去 | 位置のない生存MEMBER辺の限定修正 | 出現のない中間親、他種の辺の出所、複数構成の追加例 |
| OS | Linuxの独立コアとアプリを実行 | 各OSのパス・プロセス・配布・DB切替を実行して確認 |
| GUI・検索順位・性能・公開原子性 | 今回の厳密DB比較からは導けない | それぞれの観測と障害注入・規模別基準を追加 |

既存の [GAP一覧](../../../architecture/evolution-plan.md) と契約台帳を使って、対象契約・必要な入力・受入条件を指定して次の作業を始める。
