# 006 — 公開した証跡の欠落と訂正

作業日: 2026-10-30（UTC）。基準: `6eb332cac35eb6f0f61e754a3317415f654fd807` からの作業ツリー。
[005の統合検証](../005-portable-core-and-verification/report.md)の後、[PR #2](https://github.com/yuki-inaho/Sourcetrail/pull/2)のクリーンなCI環境が、ローカルで存在した証跡1点のコミット漏れを検出した。本バッチは公開結果の訂正であり、本体・試験・環境のコード変更を含まない。

## 観測と原因

[失敗したCI](https://github.com/yuki-inaho/Sourcetrail/actions/runs/41003049508)では、実アプリのビルドと全10 CTestスイートが成功した。その後の `verify-docs` が `evidence/baseline-corrected/build-inputs.json` への参照切れを報告して終了コード1となった。TLA+と独立Rust適合の後続ゲートは、このCIでは未到達であり成功と数えない。

`build-inputs.json` は修正のみの中間ビルドを識別する小さなJSONであり、既存の作業ディレクトリには存在していた。しかし `.gitignore` の `build-*` が任意階層の同名ファイルにも適用され、追加されていなかった。作業ツリーの存在確認だけでは公開先への包含を確認できない。[CIの末尾抜粋](evidence/ci-failure.log)と[検査の実出力](evidence/verification.json)を残す。

## 注釈単位

### ANN-001 — 生成物の除外と検証記録の包含

`.gitignore` の `build-*` は維持し、`docs/reports/**/evidence/**/build-inputs.json` にだけ例外を追加した。欠落していた[ビルド入力記録](../005-portable-core-and-verification/evidence/baseline-corrected/build-inputs.json)を、既存ローカル内容のまま追跡する。005の本文・マニフェスト・過去ハッシュは書き換えない。バイナリーや生DBを含める例外ではない。

### ANN-002 — 文書検査を公開対象そのものに適用する

`script/verification/check_docs.py` の `check_markdown` はファイルシステム上の存在を調べる。検査器を変更せず、`git checkout-index --all --prefix` でステージ済みの追跡ファイルだけを別ディレクトリへ展開し、そこへ `--root` を指定して実行した。修正前の `git archive HEAD` でも同じ参照切れを再現し、修正後のexportでは参照検査が成功することを確認する。

この検査は `VERIFICATION-001` に関連する検証手順の補強であり、プログラムの意味的な同等性を追加で証明するものではない。アーカイブにGit履歴はないため、基準コミットの可用性は通常の作業ツリーに対する `verify-docs` でも別途確認する。

## 実行結果と範囲

実行コマンド・終了状態・対象ツリーは [verification.json](evidence/verification.json) に保存する。Gitに追跡されていなかったレポート配下のファイルは、訂正前の棚卸しでは上記1点だけだった。ソース、試験、モデル、Pixi lockには差分がないため、ローカルでは文書の通常検査と追跡内容の検査に絞り、修正コミットに対する全ゲートはPRのCIで再実行する。

本レポートの記録時点では、修正後CIの結果をまだ主張しない。公開後の結果はPRとその対象コミットのチェックから確認する。005のローカル全ゲート成功という過去の観測は保持し、今回の公開漏れと区別する。

assistant側の[独立監査](evidence/independent-review.json)でも、公開済みの42トイスナップショット、48ソースハッシュ、19契約の85参照を照合し、追加の欠落は見つからなかった。ユーザー側のローカルレビューとは区別する。

## 次の作業と受入条件

ユーザー側のローカルエージェントによるレビューは未実施。

- 対象: `VERIFICATION-001` に関係する証跡の公開手順と、[ADR-0005](../../../adr/0005-toy-project-conformance.md)で要求する再現入力。
- 入力: 本バッチ、005の修正のみのパッチとビルド入力、PR #2の対象コミットとCI。
- 受入条件: クリーンな取得で参照切れがなく、全ゲートが成功し、過去の証跡ハッシュが変更されていないこと。
- 実行する確認: `pixi run --locked verify`。新規レポートを公開する際は、ステージ済み内容だけのexportにも `check_docs.py --root` を実行する。
