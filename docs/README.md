# Sourcetrail 内部仕様・契約・改善ガイド

この文書群は、既存の探索機能の意味を確認しながらリファクタリングし、Python／C++の更新とRust等の追加を進めるための入口である。実装を確認した事項、実行して検証する契約、今後実装する設計を区別する。調査基準日は **2026-10-30**。

## 目的から探す

| 知りたいこと | 読む文書 |
| --- | --- |
| 何をするソフトで、何を保つ必要があるか | [全体構成](architecture/overview.md)、[概念・用語・内部表現](architecture/domain-model.md) |
| 索引化と更新の処理順・責務 | [索引化のライフサイクル](architecture/indexing-lifecycle.md) |
| 外部索引器が失敗したときの件数・DB・終了コード | [外部実行結果の契約](contracts/external-indexing.md)、[ADR-0007](adr/0007-external-indexer-outcomes.md) |
| 保存形式、検索、グラフ、位置、ブックマーク | [保存と問い合わせ](architecture/storage-and-query.md) |
| 同じ意味を保ったことをどう判断するか | [契約と観測プロファイル](contracts/README.md)、[機械可読の契約台帳](contracts/catalog.json) |
| 人工的な小さい対象を何のために設計したか | [トイプロブレムの仕様と検査方法](contracts/toy-problems.md)、[実行対象・期待値](../tests/toy_projects/README.md) |
| 再利用・可搬性・Rustへの移植をどう確かめるか | [値処理とアダプターの分離](adr/0006-portable-refresh-core.md)、[C++／Rust共通の値入力](../tests/portability/refresh_vectors.json) |
| TLA+で何を検証し、何を検証しないか | [形式仕様と実行手順](contracts/formal/README.md) |
| なぜその境界・方式にしたか | [ADR一覧](adr/README.md) |
| 新しいPython／C++／Rustをどう追加するか | [言語対応の境界と改善計画](architecture/language-compatibility.md)、[対応能力プロファイル](contracts/language-profiles.json) |
| 不明点・未検証範囲・次の受入条件 | [改善順序とGAP一覧](architecture/evolution-plan.md) |
| ローカルのエージェントに調査を引き継ぐ | [注釈・作業レポート](reports/README.md)、[リポジトリ内スキル](../.agents/skills/annotate-contract-batch/SKILL.md) |
| ビルド・テストを再現する | [pixi開発環境](pixi-development.md) |

## 最初に実行すること

リポジトリのルートで実行する。

```sh
pixi install --locked --all
pixi run --locked verify
```

`verify` はアプリケーションのビルドと既存／回帰／E2E／トイ対象／契約テスト、外部索引器の人工障害対象、文書の参照整合性、TLA+の有限モデル検査、独立したC++コアとRust参照実装の適合試験を実行する。Javaは `formal`、C++／Rustの値契約は `portability` の独立環境に固定する。TLCは公式リリースの固定ハッシュを確認して取得する。

```sh
pixi run --locked test-contracts
pixi run --locked test-toys
pixi run --locked verify-docs
pixi run -e formal --locked verify-models
pixi run -e portability --locked verify-portability
```

各コマンドの成功は対象範囲での証拠である。モデル検査でアプリケーション全体を証明した、新版言語の対応が完了した、画像を注釈した、という意味にはならない。

## 識別子と検索

契約は `REFRESH-001`、設計判断は `ADR-0001`、未解決事項は `GAP-001` のような安定した識別子で追う。契約台帳の `sources` は実装、`verification` は実行試験またはモデル、`docs` は説明に接続する。

```sh
rg 'REFRESH-001' docs src script tests
rg 'GAP-00[1-9]|GAP-01[0-2]' docs/architecture
rg 'planned|characterized' docs/contracts/catalog.json
rg 'Rust|Python|C\+\+' docs/architecture/language-compatibility.md
```

レポートは日付／バッチ単位で保存し、対象の種類、基準コミット、ファイルのハッシュ、判断の根拠、未解決事項、次の作業を残す。既存レポートを後の実装に合わせて書き換えず、新しいバッチから参照する。

## 文書の保守

コードの変更時には、影響する契約IDと能力プロファイルを特定する。保存する意味が同じなら比較を通し、仕様を変えるなら理由と差をADR・試験・レポートに残す。`verify-docs` は参照切れ、存在しない実装根拠、契約IDの重複等を検査するが、説明の正しさや調査範囲の完全性を自動証明するものではない。

既存の `docs/documentation/` と `docs/readme/` は利用者向け説明の画像資産として残している。今回の内部仕様・注釈作業の対象と、画像のラベル付け作業は別に指定する。
