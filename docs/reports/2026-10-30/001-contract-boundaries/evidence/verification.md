# 初回注釈バッチの実行記録

作業日: 2026-10-30（Asia/Tokyo）。作業基準: `1bc605e8bea8d75abd87121e704c90caa380e44b` からの未コミット差分を含む。
以下はこのバッチで実際に実行した確認であり、後続の統合検証の代替ではない。

## 形式モデル

リポジトリ直下で実行。

```sh
python3 script/verification/check_models.py --offline
```

出力:

```text
Checking refresh-mixed ...
  PASS: {'generated': 627264, 'distinct': 522720, 'pending': 0}
Checking refresh-single-relation ...
  PASS: {'generated': 82944, 'distinct': 69120, 'pending': 0}
Checking refresh-negative-control ...
  PASS: {'generated': 25, 'distinct': 25, 'pending': 5}
```

実行器の終了コード: `0`。負の対照の TLC 自体は期待した不変条件違反により `12`。
実行時はホストの Java 17.0.20 を使用した。TLC は公式 v1.7.4、SHA-256 は実行器に固定した値と一致。
`--offline` は事前取得済み JAR を検証して使用したという意味で、未取得の状態での取得を省略可能にするものではない。
正確な引数・モデルハッシュは [formal-summary.json](formal-summary.json)、反例は [refresh-negative-control.log](refresh-negative-control.log) に保存した。

## 実行器の誤判定防止テスト

```sh
.pixi/envs/default/bin/python -m pytest -q tests/contracts/test_models.py
```

出力:

```text
..............                                                           [100%]
14 passed in 0.05s
```

終了コード: `0`。破損した JAR、オフライン時の未取得、通常モデルの未完了、期待外の失敗を成功として扱わないことを確認した。

## 文書・レポート形式

```sh
.pixi/envs/default/bin/python -m pytest -q tests/contracts/test_docs.py
.pixi/envs/default/bin/python script/verification/check_docs.py
```

出力:

```text
...........................                                              [100%]
27 passed in 0.21s
{"passed": true, "markdown_files": 20, "contracts": 16, "language_profiles": 6, "reports": 1, "error_count": 0}
```

両コマンドの終了コード: `0`。記録時点の文書に対する構造検査であり、意味の網羅性の保証ではない。
ソースが変わった後でも過去のレポートを現在の HEAD に合わせないこと、`base-commit` モードは記録した版に照合することもテストした。

## スキルの形式

このセッションの skill-creator に付属する `quick_validate.py` に、`.agents/skills/annotate-contract-batch` を渡して実行。
結果は `Skill is valid!`、終了コード `0`。公開済みの旧レポートを改変しない手順と、画像がない場合に実施済みとしない制約を記載した。
この形式検査から、別のエージェントによる実運用の品質まで保証するものではない。

## ここに含めない実行

この記録は、全 C++／Python 回帰・E2E、GUI、画像注釈、ユーザー側ローカルエージェントのレビューについての実行証跡ではない。
全体の受入結果は統合検証の記録で別途判断する。
