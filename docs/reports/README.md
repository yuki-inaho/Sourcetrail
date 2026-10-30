# 注釈と検証の作業レポート

このディレクトリは、少数単位のコード・仕様の調査と、ローカルエージェントへの追加作業の引き継ぎを保存する。
現在の形式は **source（コード・仕様）** を対象にする。画像入力は提供されていないため、今回のレポートに画像アノテーションの実施件数は含めない。

## ディレクトリ

| パス | 用途 |
| --- | --- |
| `_templates/report.md` | 人が読むレポートの雛形 |
| `_templates/manifest.json` | 機械が読む注釈一覧の雛形 |
| `YYYY-MM-DD/NNN-topic/manifest.json` | 1〜10 単位の入力・根拠・契約・未解決事項 |
| `YYYY-MM-DD/NNN-topic/report.md` | 何を、どの方法で調べ、何が分かったか |
| `YYYY-MM-DD/NNN-topic/evidence/` | 実行結果など、レポートの主張を支える最小限の証跡 |

日付とタイムゾーンは各バッチに記録する。001〜003と007以降は Asia/Tokyo、004〜006は当時の実行環境の UTC を使う。
バッチの番号はその日のディレクトリ内で重複させない。レビュー・訂正・再検証は、新しい番号で元のバッチを参照する。

## バッチ一覧

| 日付・バッチ | 対象 | 件数 | 次のレビュー |
| --- | --- | ---: | --- |
| [2026-10-30 / 001-contract-boundaries](2026-10-30/001-contract-boundaries/report.md) | 更新計画・保存・言語・検索・形式仕様の境界 | 10 source 単位 | ローカルエージェントによる独立レビュー待ち |
| [2026-10-30 / 002-independent-review](2026-10-30/002-independent-review/report.md) | 別担当による時刻・DB公開・問い合わせの独立読解 | 3 source 単位 | assistant側の読解を記録、ユーザー側レビューは未実施 |
| [2026-10-30 / 003-integration-verification](2026-10-30/003-integration-verification/report.md) | 全725テスト・形式モデル・意図した修正の統合確認 | 4 source 単位 | 同じ版での再実行と後続改善のレビュー待ち |
| [2026-10-30 / 004-toy-project-design-and-baseline](2026-10-30/004-toy-project-design-and-baseline/report.md) | 人工C++／Python対象の設計・14段階の基準・発見した欠落 | 5 source 単位 | 失敗した元基準を保持し、修正と構造変更を別々に確認 |
| [2026-10-30 / 005-portable-core-and-verification](2026-10-30/005-portable-core-and-verification/report.md) | 可搬コア・共通コマンド・Rust参照移植・797ケース・全14観測一致 | 9 source 単位 | assistant側の指摘を解消、ユーザー側のレビュー待ち |
| [2026-10-30 / 006-published-evidence-repair](2026-10-30/006-published-evidence-repair/report.md) | CIで検出した証跡の追跡漏れと、Git indexだけでの文書再検査 | 2 source 単位 | 元の失敗と訂正を保持、ユーザー側のレビュー待ち |
| [2026-10-30 / 007-external-indexer-failure-baseline](2026-10-30/007-external-indexer-failure-baseline/report.md) | 人工外部索引器の設計と、実行失敗の誤成功・旧索引置換の再現 | 3 source 単位 | 独立した期待と失敗基準を保持、修正後の照合とユーザー側レビューへ |
| [2026-10-30 / 008-external-indexer-outcomes](2026-10-30/008-external-indexer-outcomes/report.md) | 外部実行の成否・候補破棄・終端通知、838ケース、14観測一致とTLA+の検証 | 10 source 単位 | assistant側指摘と観測器の初期状態認識を修正、ユーザー側レビュー待ち |

## 入力版と履歴

各バッチは `source_revision.base_commit` に調査の基準コミットを記録する。

- `mode=base-commit`: 対象をそのコミットから読んだ記録。
- `mode=working-tree`: そのコミットから作業した未コミット差分も含む。対象の内容は各単位の SHA-256 と抜粋で識別する。基準コミットに新しいファイルや変更後の内容が存在するという意味ではない。

公開後のレポートは履歴として保持する。ソースが進んでも過去のハッシュを現在の HEAD に合わせない。
後続レビューは基準版・対象スナップショット・最新状態のどれを評価するかを明記する。履歴が足りない場合は、その履歴を取得してから解釈する。

## 注釈に必要な項目

マニフェストと本文を `ANN-001` などの ID で対応させる。各注釈に、パス、検索できるシンボル、読んだファイルの SHA-256、短い原文抜粋、関連契約 ID、観測、未確定点、次の作業を残す。
「読んで確認した」「実行した」「推論した」「まだ分からない」を区別する。関数名、試験名、ドキュメントの存在だけでは意味上の保証にならない。

契約 ID は [契約カタログ](../contracts/catalog.json) を参照する。改善によって意図的に挙動を変えるときは、同等性を維持するリファクタリングと分けて記録する。

## レポートの検査

```sh
pixi run --locked verify-docs
```

[check_docs.py](../../script/verification/check_docs.py) は、新しい内部文書のローカルリンク、契約 ID、カタログのソース・検証アンカー、バッチ構造、入力版の表記、証跡の存在を検査する。
Git 履歴があるチェックアウトでは基準 SHA がコミットであることも確認し、`base-commit` の場合は記録した版の内容・ハッシュ・抜粋に照合する。アーカイブでは SHA の形式と記録モードを検査する。
過去のソースハッシュと現在の HEAD は比較しない。意味の正しさ、全文の網羅性、画像注釈の品質、任意の Markdown 拡張構文は保証しない。

新しいレポートを作るエージェントは、リポジトリ内の [annotate-contract-batch](../../.agents/skills/annotate-contract-batch/SKILL.md) を利用する。
レポートを読むローカルエージェントは、本文の「次の作業と受入条件」を入力にして、検査結果と追加作業を次のバッチへ記録する。
