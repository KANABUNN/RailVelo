# 実行確認と受入範囲

確認日：2026-10-20。作業環境：Windows、Python 3.14.6、SQLite 3.50.4。

| 項目 | 結果・証跡 |
| --- | --- |
| 前工程SQLiteの原本保全 | 52ファイルのSHA-256一致。指定元を変更せずコピー |
| 前工程のデータ検証 | 30/30。`upstream-validation.json` |
| 前工程の接続試験 | 5/5。`upstream-topology-tests.txt` |
| 今回のSQLite/JSON生成 | 22/22。`data-quality.json` |
| DB再生成 | 繰り返し生成で同一SHA-256。`data-quality.md` |
| Python自動テスト | **36/36成功**。`test-results.txt` |
| GPS合成走行評価 | **17シナリオ・1,213観測**。`evaluation.json`、`evaluation.md` |
| 同梱SQLiteによる全区間リプレイ | JSON版と同一結果。自動テストと`release-checks.json` |
| Swift Package・XCTest | ソースと12テストを作成、静的確認。**コンパイル・実行未確認** |
| Python/Swift共通データ比較 | 比較プログラムと全件CI手順を作成。**両実装の実行比較は未実施** |
| iOS Simulator / iPhone実機 | **未実施** |
| 実走GPS | **ログなし、未評価** |

## 合成全区間で確認した動作

門司港〜博多と逆方向の連続観測に対し、路線、方面、エッジ上の位置、前後駅、次に通る駅までの線路弧長を算出した。順方向の路線・方向は確定した観測の100%で正解、起動期間を除く有効観測に対する確定率98.05%。逆方向は100%・99.35%。詳細な分母、状態件数と処理時間は `evaluation.md` に記載する。

誤差は真値もN02線形から生成した場合の値であり、地図誤差や現地の番線差を含まない。トンネル復帰を模したケースは確定率43.33%と低く、保留が長い。GPS実走精度、実トンネルの復帰性能、到着・発車の実測時刻精度を合格と扱わない。

## 再実行

ルートフォルダーで次を実行する。ネットワーク通信・有料APIは不要。

```powershell
python scripts/build_network.py
python scripts/generate_fixtures.py
python -m unittest discover -s tests -v
python scripts/evaluate.py --save-results fixtures/results
python scripts/replay.py data/railway.sqlite fixtures/corridor_full.jsonl --output replay.jsonl
```

前工程の30検証と5試験はGIS依存が別途必要。`data-quality.md` を参照。

SwiftはmacOS/Xcodeで `swift test --package-path swift` と `.github/workflows/swift.yml` のSimulator・全共通データ比較を実行する。現在のフォルダーにGitリモートがないためCIを起動していない。将来のCIが成功するまで、SwiftとPythonの同等性は未確認のままとする。

## 次工程の条件

`SWIFTUI_HANDOFF.md` に入力頻度、直列呼出し、表示項目、欠測タイマー、駅名IDの参照、未確定・予測表示を整理した。画面実装後にSwiftビルドと実走ログによる検証を行い、イベント閾値、信号待ち、折尾の駅線形、並走と直通、端末性能・電池消費を評価する。
