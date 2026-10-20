# RailVelo Swift package — v0.4

更新日: 2026-10-21。アプリの構成と操作は [ルートREADME](../README.md)、実行結果は [検証記録](../docs/VALIDATION.md) を参照してください。

Swift 5.9以上、iOS 16以上／macOS 13以上を対象としたSwift Packageです。
外部のSwift依存ライブラリーはなく、SQLiteはOS付属のsqlite3を利用します。

- `RailVeloCore`: Foundationのみを使用するグラフ、HMM前向きフィルター、駅イベント。
- `RailVeloSQLite`: 読み取り専用SQLiteからグラフを読み込む独立したアダプター。
- `RailVeloLocation`: CLLocation → Observation変換、共通`ObservationSource`、実GPSとJSONLリプレイ。
- `RailVeloRecording`: 有効速度・最高速度、走行履歴SQLite、CSV、間引きしたグラフ点。
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
取得してください。iOSの`CoreLocationSource.start()`は背景更新を有効にするため、
ホストの`Info.plist`に`UIBackgroundModes`の`location`が必要です。付属iOSアプリは
この設定と用途説明を持ち、実GPSの記録中だけ開始し、一時停止・終了時は停止します。
前面で開始したWhen In Useの更新を継続する構成で、Always許可を要求するAPIは呼びません。
OS終了後の自動再開と無欠測継続は保証しません。

CoreLocationSource自体は欠測タイマーを持ちません。付属アプリのRideViewModelは
現在表示の観測時刻から5秒以上経過すると速度・精度・現在の推定を無効にします。
処理待ちの結果も描画直前に鮮度を確認します。受信が5秒以上途絶えた場合だけ欠測観測を
入力し、CSV出力などの処理待ちだけで架空のGPS欠測行を作りません。
停止中の新しい実測値も到着判定に必要なため、distanceFilterはkCLDistanceFilterNoneです。
更新間隔と電池消費の調整は、連続した停車観測を維持する形でホストアプリ側で行います。
最後の実測以後に測位が届かない場合、アプリのタイマーから現在時刻とlat/lon=nilの
Observationを渡すと、上限付き予測・lost判定を進められます。

## 記録・表示との接続

`RideProcessor(network:)`を乗車ごとに作成し、`process(_:receivedAt:)`へ観測を順に渡します。
実GPSでは受信時刻も指定し、10秒より古い観測・5秒より未来の観測を除外します。
リプレイは元の取得時刻を保持するため、受信時刻の引数を省略します。速度の採否と
マッチ結果は`RecordedSample`に分けて保持し、実測速度が無効なら`speedKmh`はnilです。
無効な速度を予測速度や0 km/hで埋めません。`resetContinuity()`はpause/resumeの
連続性を切り、同じセッションの最高速度を維持します。

`RideStore(url:)`は線路DBと別の書き込み可能なローカルSQLiteを開きます。
`begin`、`append`、`setStatus`、`recoverInterrupted`、`summaries`、`points`、
`exportCSV`、`delete`で記録と参照を扱います。`append(_:to:recordedAt:)`の保存時刻は
GPS/リプレイの観測時刻と分けて保持します。付属アプリは実際の保存時の壁時計を渡し、
復旧時の終了時刻は開始時刻と最終保存時刻の大きい方にします。1観測の関連更新はトランザクションで
保存し、起動時の未終了セッションは中断として復旧します。記録中・一時停止中の削除は
拒否します。保存先のファイル保護・バックアップ除外・CSV共有はホスト側の責務で、
付属iOSアプリに設定を実装しています。実機での挙動は未検証です。

Matcher、RideProcessor、RideStoreは各インスタンスを同じ直列実行環境で使います。
付属アプリは専用キューで推定と保存を順に処理し、MainActorへ画面結果を戻します。
全観測を画面用配列へ溜めず、直近5分・最大2400点と全体用最大1200点に制限します。
`SpeedPoint.segment`を線の系列へ渡し、欠測やpause前後を連結しないでください。

`ReplayObservationSource(url:rate:)`は単調増加する取得時刻のJSONLを読み、既定25倍速で
観測を通知します。読み込むファイルは20MBを上限とし、空データ・不正な時刻は拒否します。
付属アプリでは実GPS/リプレイを開始前に選び、履歴・CSVにもモードを保存します。

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

Windowsを主な編集環境とし、ビルド・試験はmacOS CIで実行しています。
`.github/workflows/swift.yml`の [成功run](https://github.com/KANABUNN/RailVelo/actions/runs/39447558500)
でPython36件、Core/SQLite 12件＋Recording 17件のXCTest、全17共有fixtureのPython/Swift比較、
Core Location/SQLiteライブラリのiOS Simulator向けビルドが成功しました。
対象commitは`e206e23aacaaf9dcc298c54557808fda13ce40ba`、Xcode 16.4 / iOS Simulator 18.5 SDKです。

`.github/workflows/ios.yml`は付属アプリのビルド・Simulatorリプレイ確認を行う別のworkflowです。
[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39453148802) はcommit `8808fdd`、macos-26 arm64、
Xcode 26.6（17F113）/ iOS 26.5 SDK / iPhone 16 Simulator runtime 26.5で成功しました。
Simulator/端末向け署名なしアプリビルド、built Info.plistと同梱リソースの検査、リプレイDBの
5観測・有効速度5件・matched3件、中断復旧、ライト/ダーク画像の輝度検査と目視を確認しました。
Swift/Python試験と全fixture比較は上記engine CIが担当し、アプリCIでは重複実行しません。
グラフ目視・UI全操作・VoiceOver、署名・TestFlight・iPhone実GPS・背景・電池・実走は未検証です。
初期のNetwork/type guardのコンパイルとpkg-config経由のホストdylib参照の問題は修正済みです。
engineのrunnerは`macos-15-intel`、アプリは`macos-26`（arm64）です。関連pathのみの自動実行と
ブランチ単位のconcurrencyを設定しています。
最新の実行状況は [検証記録](../docs/VALIDATION.md) を確認してください。
