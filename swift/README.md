# RailVelo Swift package

Swift 5.9以上、iOS 16以上／macOS 13以上を対象としたSwift Packageです。
外部のSwift依存ライブラリーはなく、SQLiteはOS付属のsqlite3を利用します。

- `RailVeloCore`: Foundationのみを使用するグラフ、HMM前向きフィルター、駅イベント。
- `RailVeloSQLite`: 読み取り専用SQLiteからグラフを読み込む独立したアダプター。
- `RailVeloLocation`: CLLocation → Observation変換と、任意で利用できる測位ソース。
- `railvelo-replay`: Python版と同じJSONL観測値を処理するコマンド。

```swift
import RailVeloCore
import RailVeloSQLite
import RailVeloLocation

let network = try SQLiteNetworkLoader.load(url: bundledDatabaseURL)
let matcher = MapMatcher(network: network)
// CLLocationManagerDelegate等で受け取ったCLLocationを変換する。
let result = matcher.update(Observation(location: location))
```

`MapMatcher`は走行ごとの状態を保持します。インスタンスごとに一つの直列実行環境で
`update`を呼び、別走行では`reset()`を呼ぶか新しいインスタンスを作成してください。
CoreLocationSourceのコールバックはMainActorで呼ばれます。計算を別Actorへ移す場合は、
Observationのみを渡して、そのActor内でMatcherを生成・保持してください。

アプリ側に`NSLocationWhenInUseUsageDescription`を設定し、測位を開始する前に権限を
取得してください。バックグラウンド測位、電池消費の調整、位置情報の保存・削除UIは
ホストアプリ側の実装項目です。CoreLocationSourceは欠測タイマーを持ちません。
停止中の新しい実測値も到着判定に必要なため、distanceFilterはkCLDistanceFilterNoneです。
更新間隔と電池消費の調整は、連続した停車観測を維持する形でホストアプリ側で行います。
最後の実測以後に測位が届かない場合、アプリのタイマーから現在時刻とlat/lon=nilの
Observationを渡すと、上限付き予測・lost判定を進められます。

`status == "matched"`は実測に基づく確定、`predicted`は欠測中の短時間推定です。
`uncertain`の候補座標は確定位置として表示せず、`candidates`と信頼度を併用してください。
`nextStationId`は物理的な次の通過駅であり、次の停車駅ではありません。
confidenceは与えたグラフ内の相対支持率で、実走行精度を保証する値ではありません。
到着は停車確認後、通過は駅中心を越えて駅の判定範囲から退出した後に発行されます。
駅中心の少し先で停車した場合も、通過と到着を重複して発行しないためです。
イベントのtimestampは推定された到着・通過・発車時刻で、発行時刻より前になる場合があります。

JSON読書きには`RailVeloJSON.decoder()`／`encoder()`を使用します。
キーはリポジトリー直下の[CONTRACT.md](../CONTRACT.md)と同じsnake_caseです。
距離単位はm、速度はm/s、時刻はUTC Unix秒、座標はWGS84です。

```sh
swift test --package-path swift
swift run --package-path swift railvelo-replay --network fixtures/synthetic_network.json --input fixtures/normal.jsonl --output artifacts/normal.swift.jsonl
python scripts/compare_replays.py artifacts/normal.python.jsonl artifacts/normal.swift.jsonl
```

比較は識別子・状態・方向を一致させ、距離2m、確率・進捗率0.03、
イベント推定時刻0.00001秒の数値許容差で判定します。

作業環境のWindowsにはSwift／Xcodeが存在しないため、作成時点ではSwiftビルド、
Pythonとの実行結果比較、iOS Simulator、iPhone実機の確認は未実施です。
`.github/workflows/swift.yml`はmacOS上のテスト、Simulatorビルド、全共有fixture比較を
定義していますが、workflowの存在自体は成功証跡ではありません。
