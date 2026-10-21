# RailVelo — JR九州 鉄道走行モニター v0.5

JR九州・鹿児島本線の門司港〜博多を対象に、GPS速度と線路上の推定位置・駅間情報を表示するSwiftUIアプリです。既存のオフライン推定エンジンを再利用し、Core Location、Swift Charts、走行履歴SQLite、CSV共有、合成GPSリプレイを接続しています。推定に外部APIやクラウドへのGPS送信は使用しません。

**v0.5の本人限定TestFlight配布と、iPhone 16での実GPS基本動作確認ができました。** 配布版は`0.5.0 (500.7.1)`。導入・起動、GPS精度・静止/歩行速度・グラフ表示、CSV保存に加え、「常に許可・正確な位置情報オン」で約5分のロック中のグラフ上の記録継続・解除後の画面表示を本人申告で確認しました。約8分の別アプリ使用後もグラフに不審な動きはなく、戻った後の速度変化とその他異常なしを確認。終了済み履歴はアプリ再起動後も同じ内容で残り、保存済みCSVも開けてエラーなしとの報告を得ています。

同じアプリsourceのCIでPython76件・Swift32件・17シナリオ比較、両署名なしビルド、3件のUI試験が成功。配布処理も実署名・証明書検査・Appleの`VALID`/`INTERNAL_ONLY`確認まで成功しました。速度・位置の定量精度、連続線、ロック解除後の新しいGPS値の更新、10分以上の背景試験、長時間/電池・実走評価は未確認です。最新の証跡と未完了項目は[検証記録](docs/VALIDATION.md)を確認してください。

## アプリに接続した機能

- 大きな現在速度、セッション最高速度、水平/速度精度、GPS・走行状態。無効値、古い測位、不自然な速度変化や座標跳躍を検査し、採用しない理由を保存します。実GPSの現在表示は観測時刻から5秒で失効し、処理待ちの古い結果で戻しません。
- 60秒・5分・全体の速度グラフ。取得時刻を横軸に使い、欠測・速度無効・一時停止の間は線を切ります。
- 路線、方面、前後駅、次に通る駅までの線路距離、駅間進捗、推定の候補支持度。
- 記録開始・一時停止・再開・終了。履歴の再読込、確認付き削除、UTC/WGS84/単位/有効性を明示したCSV共有。
- 実走調査用のGPSエラー・権限・前面/背景状態・受信/保存開始時刻を端末内へ記録。既存CSVの先頭36列を保ち、末尾に3列を追加します。[非公開ログの解析・正解記録様式](docs/RIDE_EVALUATION.md)を用意しています。
- 実GPSと、同梱の門司港〜博多の合成走行を25倍速で再生するモード。履歴にもモードを残します。
- 日本語、ダークモード、iPhone縦画面、基本的なVoiceOverラベル。実機の表示・操作性は受入試験が必要です。

実GPSの記録中だけ背景位置情報を有効にする構成です。OS終了後の無欠測継続は保証せず、再起動時には未終了の記録を中断として保存します。履歴は端末内に保存し、バックアップ除外と端末ファイル保護を設定しています。CSV共有は利用者が選ぶ共有先へ渡します。背景動作・ロック中の保護・電池消費は実機で確認してください。

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

配布ファイルの `MANIFEST.sha256` は、Gitへステージした正規内容のSHA-256一覧です。Windowsの改行変換後の作業ファイルとは区別します。変更対象をステージした後に再生成・照合し、生成した一覧もステージしてから反映します。

```powershell
python scripts/update_manifest.py
python scripts/update_manifest.py --verify
```

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
| `ios/RailVelo.xcodeproj` | 共有scheme `RailVelo` を持つiPhoneアプリのXcodeプロジェクト |
| `ios/RailVelo/` | SwiftUI画面、Charts、ViewModel、背景位置情報・プライバシー設定 |
| `swift/` | Core / SQLite / Location / Recordingの独立モジュール、リプレイCLI、Swiftテスト |
| `data/railway.sqlite` / `data/network.json` | 検証済みの計算用ネットワーク |
| `scripts/` | データ変換、合成GPS生成、評価、Python/Swift結果比較、リプレイ |
| `fixtures/` / `tests/` | 観測値と正解を分離した共通データ、自動テスト |
| `docs/TECHNICAL_DESIGN_v0.5.md` | 本人限定TestFlight・署名・実機受入と実走診断の設計 |
| `docs/TECHNICAL_DESIGN_v0.4.md` | 継承したアプリ・入力分離・速度採否・履歴・背景の設計 |
| `docs/TECHNICAL_DESIGN_v0.3.md` | 継承した推定方式・入力出力・既定値 |
| `docs/APPLE_SETUP.md` | Windows中心のビルド、署名、Apple設定、本人用TestFlight導入 |
| `docs/DEVICE_TEST_PLAN.md` | 許可・欠測・背景・OS終了・電池・実走の試験手順 |
| `docs/SIMULATOR_UI_VALIDATION.md` | 実グラフ・記録操作・履歴・共有画面・アクセシビリティの確認 |
| `scripts/analyze_ride.py` / `docs/RIDE_EVALUATION.md` | 非公開の実走CSVと本人の正解記録・補助測定から評価 |
| `docs/templates/` | 実機結果、駅イベント・位置の正解、電池等の記録様式 |
| `.github/workflows/` | Swift/Python比較とiOSアプリのビルド・Simulator検証の定義 |
| `docs/evaluation.json` / `docs/evaluation.md` | 実行済み評価の定量結果 |
| `docs/data-quality.md` / `docs/data-quality.json` | 前工程と今回のSQLite検証 |
| `docs/WORK_LOG.md` | 実施内容と未検証範囲 |
| `vendor/n02/` | 前工程の原本コピー、取得・変換コード、元SQL、公式ZIP、出典・品質記録 |

## Swift / iPhone

アプリはiOS 16以上、Swift PackageはiOS 16 / macOS 13以上を対象とし、Package manifestはSwift tools 5.9です。iPhone 16では端末の対応する搭載OSを使います。アプリの外部Swiftライブラリ依存はなく、SQLiteはOS付属のライブラリです。元データからの再生成時にだけ別途GIS依存が必要です。

Macを使用できる場合は `ios/RailVelo.xcodeproj` をXcodeで開き、scheme `RailVelo` とiPhone Simulatorを選んで起動します。プロジェクトはローカル `swift/` を参照し、線路DBとリプレイfixtureを同梱します。アプリの実機署名には本人のTeamと配布設定が必要です。最低対応OSとアップロード用SDKの要件、署名資料・APIキーの扱いは [Apple手順](docs/APPLE_SETUP.md) を参照してください。

macOSでの署名なしビルド例：

```sh
swift test --package-path swift
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS Simulator' -derivedDataPath artifacts/DerivedData CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS' -derivedDataPath artifacts/DeviceBuild CODE_SIGNING_ALLOWED=NO build
```

署名付きの個人導入は内部TestFlightで実施しました。App IDは`jp.kb-dev.railvelo`、App Store Connectアプリは「RailVelo」（ID `6824978233`）です。内部グループ「本人検証」は本人1人・`0.5.0 (500.7.1)`のビルド1件、自動配信オフ・公開リンクなし。署名・アップロード・Apple処理と本人への割当が成功し、本人から端末への導入・起動、実GPSの基本表示とCSV保存成功の回答を得ています。証跡と実機試験の範囲は[検証記録](docs/VALIDATION.md)を確認してください。秘密鍵や証明書のパスワードはリポジトリへ保存しません。

導入後は「リプレイ」で開始すると同梱合成GPSを再生します。「実GPS」は前面で開始し、位置情報を許可します。停止・再開・終了は画面下の操作、保存済み走行は履歴からグラフ参照・CSV共有・削除を行います。

macOSにて共通データを処理・比較する例：

```sh
swift test --package-path swift
python3 scripts/replay.py fixtures/synthetic_network.json fixtures/normal.jsonl --output python-normal.jsonl
swift run --package-path swift railvelo-replay --network fixtures/synthetic_network.json --input fixtures/normal.jsonl --output swift-normal.jsonl
python3 scripts/compare_replays.py python-normal.jsonl swift-normal.jsonl
```

配布したアプリsource `afd55bb`の[engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39531707938)で、全17シナリオ比較、Swift32件、Python76件、Swift生成CSVのPython解析、iOS向けライブラリのビルドが成功しました。同じsourceの[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39531634651)もXcode 26.6 / iOS 26.5 SDKで両ビルド・合成リプレイ・中断復旧・3件のUI試験が成功し、グラフ3期間・記録操作・履歴/削除・共有画面・明暗/大きい文字を実画像で確認しました。25秒間隔の合成入力による点描画と、実GPSの連続線・実際のVoiceOverは区別します。[Simulatorの詳細](docs/SIMULATOR_UI_VALIDATION.md)

標準GitHub-hosted runnerはpublicリポジトリで無料、privateリポジトリでは含有枠超過時に有料です。公開前監査と履歴整理の後、利用者が公開設定を変更しました。公開状態はGitHubのリポジトリ情報で確認済みです。engine CIは`macos-15-intel`、アプリCIは`macos-26`（arm64）を使用し、関連ファイルの変更だけを対象にし、同じブランチの古い実行を取り消して重複を抑えます。結果は [検証記録](docs/VALIDATION.md)、課金の条件と代替手段は [Apple手順の費用説明](docs/APPLE_SETUP.md#2-osxcode費用) を参照してください。

## データの範囲と制約

対象は32駅・代表経路117エッジ・別経路候補3エッジ。周辺別路線の60エッジも比較候補に含みます。距離はN02の代表線形に沿った弧長で、営業キロや実際に乗車した番線の距離ではありません。

対象外路線・別経路では、駅順や距離の裏付けが足りない場合に方面・前後駅・残距離を確定しません。幾何的な交差から接続を補作していないため、他路線への実際の転線・直通追跡は追加データと検証が必要です。全国へ拡張できるデータ形式ですが、全国データ完成とは扱いません。

`next_station_id` は次に通過する地理上の駅です。次の**停車駅**・列車種別・列車ID・到着予定時刻は提供しません。`predicted` は欠測時の短時間予測、`uncertain` / `lost` / `rejected` は位置や路線を確定できない状態です。信頼度は候補内の相対支持度で、実世界の正解確率に較正した値ではありません。

受入が残る項目は、実GPSの定量精度と連続線・実際のVoiceOver、10分以上のロック/別アプリ中の継続と欠測・ロック解除後の新しいGPS値の更新、履歴/CSVの詳細内容の照合・記録中の中断/OS終了復旧、長時間性能と電池、実際の駅イベント・並走・トンネル復帰です。実走ログは未取得で、合成データの評価値から実走精度を確定していません。v0.1/v0.2設計書の本文は再取得できておらず、前工程の元SQLと設計対応記録を継承しています。全国対応、他路線への直通、営業上の停車駅判定には追加データと実証が必要です。

## 出典と再現

出典：[国土交通省・国土数値情報 N02 鉄道2025年度版](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html)を加工。個別データの条件はCC BY 4.0。原本ZIP、出典、加工内容を同梱し、詳細を [データ出典](docs/data-provenance.md) に記録しています。

前工程の元データからの再生成にのみ、`vendor/n02/requirements.lock.txt` のGISパッケージが必要です。元のv0.2 SQLは保存し、今回の実行用SQLiteは別ファイル・別スキーマとして生成しています。元フォルダーへの変更はありません。
