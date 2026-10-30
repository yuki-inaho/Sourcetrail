# 概念・用語・意味の境界

この文書の「現行」は [実装](../../src/lib/) から読み取れる性質であり、理想的な言語仕様全体を保証する意味ではない。設計判断は [ADR-0001](../adr/0001-semantic-observations.md) を参照する。

## 用語集

| 用語 | 意味 | 根拠となる型・実装 |
| --- | --- | --- |
| プロジェクト / Project | 設定ファイルと複数の Source Group、索引 DB、ブックマーク DB をまとめる単位 | [Project.h](../../src/lib/project/Project.h), [ProjectSettings.cpp](../../src/lib/settings/ProjectSettings.cpp) |
| Source Group | 共通の言語・ビルド設定・対象範囲を持つ入力集合。無効化されたグループは索引化から除く | [SourceGroup.h](../../src/lib/project/SourceGroup.h) |
| 索引化コマンド / IndexerCommand | ソースと作業ディレクトリ、引数等を含む、解析の実行単位 | [IndexerCommand.h](../../src/lib/data/indexer/IndexerCommand.h) |
| 翻訳単位 / translation unit | C++ ではプリプロセス設定を含むコンパイル単位。同じヘッダーでも設定により観測結果が変わる | [IndexerCommandCxx.h](../../src/lib_cxx/data/indexer/IndexerCommandCxx.h) |
| ノード / node | ファイル、名前付き記号、名前の階層をグラフに表す要素 | [StorageNode.h](../../src/lib/data/storage/type/StorageNode.h), [NodeKind.h](../../src/lib/data/NodeKind.h) |
| 記号 / symbol | 名前付き要素の定義状態を持つ記録。全ノードに `symbol` 行があるわけではない | [StorageSymbol.h](../../src/lib/data/storage/type/StorageSymbol.h) |
| 関係 / edge | 始点、終点、種別を持つ有向関係。出現場所は別の `occurrence` で表す | [StorageEdge.h](../../src/lib/data/storage/type/StorageEdge.h) |
| 出現 / occurrence | 要素とソース位置の対応。同じ呼び出し関係に複数の出現場所が付くことがある | [StorageOccurrence.h](../../src/lib/data/storage/type/StorageOccurrence.h) |
| ソース位置 / source location | ファイル、開始・終了行列、位置種別を持つ領域 | [StorageSourceLocation.h](../../src/lib/data/storage/type/StorageSourceLocation.h) |
| 不完全 / incomplete | 解析結果が完全でないと記録されたファイル。構文診断や致命的診断に関連する | [Indexer.h](../../src/lib/data/indexer/Indexer.h), [IntermediateStorage.h](../../src/lib/data/storage/IntermediateStorage.h) |
| 曖昧 / ambiguous | 一つの参照に確定した解決先を与えられない場合の情報。単なる重複ではない | [TaskExecuteCustomCommands.cpp](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp) |

## 名前と同一性

`NameHierarchy` は区切り文字と、各階層の名前・シグネチャの前置部・後置部を持つ。保存文字列には `\tm`、`\tn`、`\ts`、`\tp` という内部区切りがある。`StorageNodeData::operator<` は保存名で比較し、記号種別は名前を作った後に更新される場合がある。[NameHierarchy.cpp](../../src/lib/data/name/NameHierarchy.cpp)、[ParserClientImpl.cpp](../../src/lib/data/parser/ParserClientImpl.cpp) を参照。

したがって、表示名の最後の部分だけを同一性に使ってはいけない。`A::run(int)` と `B::run(int)`、`run(int)` と `run(double)` は異なる対象である。保存された階層とシグネチャを保持し、型種別や定義状態も観測に含める。

数値の ID は各中間結果と保存先で付け直される。`Storage::inject` は要素 ID とソース位置 ID の対応表を構築し、ノード、関係、位置、出現等を再対応付けする。プロジェクトを作り直した前後で ID が変わることは、そのまま意味の差にはならない。[Storage.cpp](../../src/lib/data/storage/Storage.cpp)

現行の保存名には言語名・ビルド構成 ID・パッケージの由来を独立した必須フィールドとして持つ共通規約がない。多言語・複数 crate・複数ビルド構成の同名衝突を扱うには、その区別を追加するか、比較範囲を限定する仕様が必要である。既存名の書き換えはブックマークにも影響するため、単なる内部変更として進めない。

## 関係の向きと種類

`ParserClient::recordReference(kind, referenced, context, location)` は API の引数順に注意する。保存される関係は **context → referenced** である。`recordSymbol` は階層の親から子へ `MEMBER` を補う。[ParserClientImpl.cpp](../../src/lib/data/parser/ParserClientImpl.cpp)

| 記録する意味 | 保存側の関係 | 代表的な向き |
| --- | --- | --- |
| 所属 | `EDGE_MEMBER` | 親スコープ → 子要素 |
| 呼び出し | `EDGE_CALL` | 呼び出し側 → 呼び出される対象 |
| 型使用・一般参照 | `EDGE_TYPE_USAGE`, `EDGE_USAGE` | 使用する側 → 対象 |
| 継承 | `EDGE_INHERITANCE` | 派生側 → 基底側 |
| 上書き | `EDGE_OVERRIDE` | 上書きする側 → 対象 |
| 型引数・特殊化 | `EDGE_TYPE_ARGUMENT`, `EDGE_TEMPLATE_SPECIALIZATION` | 対応する言語アダプターが記録する関係 |
| ファイル依存 | `EDGE_INCLUDE`, `EDGE_IMPORT` | 取り込む側 → 取り込まれる側 |
| マクロ・注釈の使用 | `EDGE_MACRO_USAGE`, `EDGE_ANNOTATION_USAGE` | 使用側 → 対象 |

`ReferenceKind` の整数と、SQLite に入る `Edge::EdgeType` のビット値は同じ体系ではない。たとえば `REFERENCE_CALL = 3` に対し `EDGE_CALL = 1 << 3` である。外部索引器や新言語が「名前が同じ列挙だから」と整数を直接流用してはいけない。[ReferenceKind.h](../../src/lib/data/parser/ReferenceKind.h)、[Edge.h](../../src/lib/data/graph/Edge.h)

グラフの表示では継承等を縦方向として扱うが、表示方向は保存された始点・終点の意味を変更しない。Rust の trait 実装を無条件に「クラス継承」に写すなど、表示都合だけの意味付けを避ける。

## 位置・内容・文字コード

位置には TOKEN、SCOPE、QUALIFIER、LOCAL_SYMBOL、SIGNATURE、COMMENT、ERROR、UNSOLVED 等がある。全文検索と画面内検索の位置は問い合わせ時に生成されるものも含む。[LocationType.h](../../src/lib/data/location/LocationType.h)

画面・Python 後処理では、1 始まりの列と終端を含む範囲を使う箇所がある。一方で、位置の「列」が UTF-8 バイト、コードポイント、UTF-16 単位のどれであるかは、外部アダプターまで含めた一つの検証済み規約としては確立していない。`ParseLocation::isValid` 自体は `fileId != 0` のみを確認する。位置の順序・範囲・文字境界は追加の契約で検査する必要がある。[ParseLocation.cpp](../../src/lib/data/parser/ParseLocation.cpp)、[TaskExecuteCustomCommands.cpp](../../src/lib/data/indexer/TaskExecuteCustomCommands.cpp)

新アダプターは、入力の文字コード、行列の起点、終端を含むかどうか、列の単位、マクロ展開位置と元ソース位置の選択を宣言し、共通形式への変換を担当する。日本語、結合文字、絵文字、改行コード、行末位置を持つ例で検査する。既存の Unicode ファイル名試験だけでは、この変換全体の保証にならない。

## 解析状態と確信度

`file.indexed` はプロジェクトの索引対象として扱われるか、`file.complete` は解析の完了状態を示す。`symbol.definition_kind` は定義なし・暗黙定義・明示定義を区別する。これらは別の軸であり、単一の「成功」フラグに潰せない。[DefinitionKind.h](../../src/lib/data/DefinitionKind.h)、[StorageFile.h](../../src/lib/data/storage/type/StorageFile.h)

C++／Java の `Indexer<T>::index` は、致命的診断があれば全ファイルを不完全にし、それ以外はエラーのあるファイルを不完全にする。中断時には中間結果を返さない。Python は別経路で、外部索引器の記録後に未解決位置から候補を追加する後処理がある。候補には `IS_AMBIGUOUS` が付く。両者の「解析終了」を同じ制御フローとして解釈しない。

## 比較する単位

比較プロファイルには、少なくとも入力集合、入力内容、解析設定、アダプター版、対象言語の版、宣言した対応能力、観測範囲、許容する正規化を含める。共通契約は同じ操作に対する同じ意味を求めるが、異なる言語のプログラム全体が同じであるとは求めない。

| 比較 | 有効な問い | 無効な結論 |
| --- | --- | --- |
| 同じ解析器の内部整理 | 名前・関係・位置・状態が保持されたか | 数値 ID が違うので不適合 |
| 解析器のバージョン更新 | 既存の対応範囲を保持し、新機能の期待も満たすか | 旧解析器が出さなかった情報は全て回帰 |
| Python と Rust の共通機能 | 定義・参照・検索等の契約をそれぞれ満たすか | 言語ごとの全グラフが同じになるべき |
| 診断改善 | 診断の有無・種別・対象位置・回復結果が妥当か | 診断文言が違うだけで意味が同じ／違うと決める |

同等性の判断に使う観測を先に固定し、その後で比較する。差が出た後に、都合の悪い項目を正規化で消す運用は禁止する。
