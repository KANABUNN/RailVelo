# RailVelo — JR九州 鉄道走行モニター v0.3

門司港〜博多のN02線路データと連続GPSから、走行路線・方面・線路上位置・前後駅・次に通過する駅までの線路距離を計算するオフラインエンジンです。Python参照実装と、iPhoneへの組み込みを想定したSwift Packageを収録しています。時刻表API・有料サービス・クラウドへのGPS送信は使用しません。

実行した検証は合成GPSによるものです。実走GPS・iPhone実機・Swift/iOSビルドの検証状況は [検証記録](docs/VALIDATION.md) を確認してください。合成データの誤差を実測精度として扱わないでください。

## まず実行する

Windows / Python 3.11以上。Pythonの推定、変換アダプター、テスト、評価は標準ライブラリだけで動きます。今回の実行環境はPython 3.14.6です。

```powershell
python scripts/build_network.py
python scripts/generate_fixtures.py
python -m unittest discover -s tests -v
python scripts/evaluate.py
python scripts/replay.py data/railway.sqlite fixtures/corridor_full.jsonl --output replay.jsonl
```

最後のコマンドは、同梱SQLiteを読み取り専用で開き、門司港〜博多の合成走行を処理します。`replay.jsonl` の各行が1観測の結果です。JSONネットワークでも同じAPIを使えます。

```python
import sys
sys.path.insert(0, "python")
from railvelo import Network, Matcher

matcher = Matcher(Network.from_sqlite("data/railway.sqlite"))
result = matcher.update({
    "timestamp": 1792440000.0,
    "lat": None, "lon": None,
    "horizontal_accuracy_m": 10.0,
    "speed_mps": None, "speed_accuracy_mps": None, "course_deg": None,
})
# GPS欠測の例。捕捉前なのでstatusはlost。
```

緯度経度はWGS84互換、時刻はUTC Unix秒、距離はm、速度はm/s、方位は北0°の時計回りです。速度計表示のkm/h変換はアプリ側で行います。

## 成果物

| 場所 | 内容 |
| --- | --- |
| `python/railvelo/` | HMM推定、幾何・グラフ、駅イベント、読み取り専用SQLiteローダー |
| `swift/` | Core / SQLite / Core Locationの独立モジュール、リプレイCLI、Swiftテスト |
| `data/railway.sqlite` / `data/network.json` | 検証済みの計算用ネットワーク |
| `scripts/` | データ変換、合成GPS生成、評価、Python/Swift結果比較、リプレイ |
| `fixtures/` / `tests/` | 観測値と正解を分離した共通データ、自動テスト |
| `docs/TECHNICAL_DESIGN_v0.3.md` | 推定方式・入力出力・既定値・拡張方針 |
| `docs/SWIFTUI_HANDOFF.md` | 次工程の画面への接続仕様と残課題 |
| `docs/evaluation.json` / `docs/evaluation.md` | 実行済み評価の定量結果 |
| `docs/data-quality.md` / `docs/data-quality.json` | 前工程と今回のSQLite検証 |
| `docs/WORK_LOG.md` | 実施内容と未検証範囲 |
| `vendor/n02/` | 前工程の原本コピー、取得・変換コード、元SQL、公式ZIP、出典・品質記録 |

## Swift / iPhone

Xcodeの「Add Package Dependencies」でローカルの `swift/` を追加し、`RailVeloCore`、`RailVeloSQLite`、`RailVeloLocation` を利用します。iOS 16 / macOS 13以上、Package manifestはSwift tools 5.9です。SQLiteはOS標準ライブラリを使います。Swiftの具体例とビルド手順は [Swift README](swift/README.md) を参照してください。

macOSにて共通データを処理・比較する例：

```sh
swift test --package-path swift
python3 scripts/replay.py fixtures/synthetic_network.json fixtures/normal.jsonl --output python-normal.jsonl
swift run --package-path swift railvelo-replay --network fixtures/synthetic_network.json --input fixtures/normal.jsonl --output swift-normal.jsonl
python3 scripts/compare_replays.py python-normal.jsonl swift-normal.jsonl
```

全シナリオ比較とiOS Simulatorビルドは `.github/workflows/swift.yml` に定義しています。ワークフローを置いたことはCI成功を意味しません。本作業フォルダーにはGitリモートがなく、GitHubへの公開・CI実行は行っていません。

## データの範囲と制約

対象は32駅・代表経路117エッジ・別経路候補3エッジ。周辺別路線の60エッジも比較候補に含みます。距離はN02の代表線形に沿った弧長で、営業キロや実際に乗車した番線の距離ではありません。

対象外路線・別経路では、駅順や距離の裏付けが足りない場合に方面・前後駅・残距離を確定しません。幾何的な交差から接続を補作していないため、他路線への実際の転線・直通追跡は追加データと検証が必要です。全国へ拡張できるデータ形式ですが、全国データ完成とは扱いません。

`next_station_id` は次に通過する地理上の駅です。次の**停車駅**・列車種別・列車ID・到着予定時刻は提供しません。`predicted` は欠測時の短時間予測、`uncertain` / `lost` / `rejected` は位置や路線を確定できない状態です。信頼度は候補内の相対支持度で、実世界の正解確率に較正した値ではありません。

## 出典と再現

出典：[国土交通省・国土数値情報 N02 鉄道2025年度版](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html)を加工。個別データの条件はCC BY 4.0。原本ZIP、出典、加工内容を同梱し、詳細を [データ出典](docs/data-provenance.md) に記録しています。

前工程の元データからの再生成にのみ、`vendor/n02/requirements.lock.txt` のGISパッケージが必要です。元のv0.2 SQLは保存し、今回の実行用SQLiteは別ファイル・別スキーマとして生成しています。元フォルダーへの変更はありません。
