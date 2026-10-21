# 実行確認と受入範囲 — v0.5 作業中

## v0.5の追加確認（2026-10-21）

**最新版engine CI成功:** [run 39526756758](https://github.com/KANABUNN/RailVelo/actions/runs/39526756758)、対象commit `3619eccf8d4bcb2638064ea41c387d02f96f426f`。Python74件、Swift32件（Core/SQLite12＋Recording20）が0失敗。Swiftが生成した実39列の人工CSVをPython解析へ渡す相互運用、17 fixture比較、iOS向けライブラリのビルドも成功した。

同commitの[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39526756727)は両ビルド・既存smoke・修正済み中断復旧まで成功した。新規UI試験はグラフ3期間の描画まで通ったが、大きい文字の速度表示と履歴スワイプ後の画面遷移で失敗した。速度文字へDynamic Type対応を追加し、リプレイを早めに一時停止して履歴画面を確認する手順へ修正した。再実行の合格を確認するまで、UI全操作・配布の受入は未完了とする。

既存v0.4の成功結果を下に保存する。v0.5では実リプレイを使用したXCUITest（グラフ描画・3期間切替・スクロール・記録操作・履歴/削除・CSV共有画面・大きい文字/明暗Accessibility Audit）を追加し、CIで実行する。実行前の項目を成功と扱わない。VoiceOverの実際の読み上げ、TestFlight配布、iPhone 16の実GPS・背景・電池、実走評価は未実施。

実走ログは既存CSVの先頭36列を維持し、受信時刻・保存処理開始時刻・診断JSONを末尾へ追加した39列へ拡張した。GPSエラー、権限、アプリ状態を端末内に記録する。保存処理開始までの経過はSQL/commit時間やCPU使用率ではない。個人の位置情報を含むファイルは`recordings/`に保存し、公開CIでは人工データだけを使う。[実走解析と記録様式](RIDE_EVALUATION.md)

署名付き配布は手動起動・内部テスト限定のワークフローを作成済み。利用者の明示許可を得て新しいDistribution証明書と生成鍵の一致、専用App Store profileの対象・期限・証明書一致、API鍵形式を実ファイルで確認した。GitHubはmainのみ・本人reviewer必須・admin bypass無効のEnvironmentに7 Secretsを登録済み。秘密値は記録しない。登録中だけの一時的な読取権限は別途明示許可を得て設定し、登録後に削除・確認した。実署名・Apple認証・アップロード成功・処理完了・本人グループへの割当・実機導入はまだ未確認。

本人の申告による実機条件はiPhone 16 / iOS 27.0.1、TestFlightインストール済み。RailVeloの導入・実GPSの合格とは扱わない。

## v0.4で確認済みの基準

前工程確認日：2026-10-20、v0.4更新日：2026-10-21。作業環境：Windows、Python 3.14.6、SQLite 3.50.4。v0.4の追加実装と実行待ち項目は以下の表で区別する。

**engine CI・アプリCIは成功。** Python36件・Swift29件・17 fixture比較、アプリの2種類のビルド、SimulatorリプレイDB・中断復旧・ライト/ダーク画像を確認した。署名・TestFlight・iPhone実GPS・背景・電池・実走は未検証。グラフ目視・UI全操作・VoiceOverも未検証である。

| 項目 | 結果・証跡 |
| --- | --- |
| 前工程SQLiteの原本保全 | 52ファイルのSHA-256一致。指定元を変更せずコピー |
| 前工程のデータ検証 | 30/30。`upstream-validation.json` |
| 前工程の接続試験 | 5/5。`upstream-topology-tests.txt` |
| 今回のSQLite/JSON生成 | 22/22。`data-quality.json` |
| DB再生成 | 繰り返し生成で同一SHA-256。`data-quality.md` |
| Python自動テスト | **36/36成功**。Windowsで再実行し、下記engine CIでも全件成功。前工程の記録は `test-results.txt` |
| GPS合成走行評価 | **17シナリオ・1,213観測**。`evaluation.json`、`evaluation.md` |
| 同梱SQLiteによる全区間リプレイ | JSON版と同一結果。自動テストと`release-checks.json` |
| Swift Core/SQLite XCTest | **12/12成功**。下記engine CI |
| Swift Recording XCTest | **17/17成功**。速度異常・古い/未来/逆行観測、pause、SQLite再読込・復旧・保存時刻・既存DB対応・ロールバック、間引き、CSV・削除を対象 |
| Python/Swift共通データ比較 | **17 fixture全件成功**。状態・識別子と数値許容差を含む共通比較による |
| iOS Simulator向けライブラリ | **Core Location / SQLiteのビルド成功**。Xcode 16.4 / iOS Simulator 18.5 SDK |
| SwiftUIアプリとXcode設定 | Xcodeプロジェクト、画面、Core Location接続、直列推定/保存、履歴、CSV、リプレイ、背景・プライバシー設定を実装。下記アプリCIでコンパイル成功 |
| iOS Simulator / 端末向け署名なしビルド | **両方成功**。Xcode 26.6（17F113）/ iOS 26.5 SDK、run 39453148802 |
| built Info.plist・同梱リソース | **検査成功**。アプリCIでscene設定と必要リソースを確認 |
| Simulatorリプレイ・DB・中断復旧 | **成功**。5観測・有効速度5件・matched3件、終了後の再起動で`interrupted`への復旧を確認 |
| ライト/ダーク画面 | **自動検査と目視成功**。実画像の背景3点平均輝度 約0.9648 / 0.0。合成速度71.7 km/h、鹿児島本線・博多方面・駅間進捗を確認 |
| グラフ目視・UI全操作・VoiceOver | **未検証**。今回の画像は画面下のグラフを含まない |
| 公開後のGitHub Actions実行 | **engine CI・アプリCIともsuccess**。対象commitとrunは下記 |
| iPhone 16への導入・前面GPS・背景GPS | **未実施** |
| 実走GPS | **ログなし、未評価** |
| 長時間・電池・端末ファイル保護・共有先 | **実機未検証** |

## v0.4のCI・Apple・公開状態

**engine CI成功:** [run 39447558500](https://github.com/KANABUNN/RailVelo/actions/runs/39447558500)、対象commit `e206e23aacaaf9dcc298c54557808fda13ce40ba`。Xcode 16.4 / iOS Simulator 18.5 SDKで、Python36件、Swift29件（Core/SQLite12＋Recording17）、iOS Simulator向けCore Location/SQLiteライブラリのビルド、17 fixture全件のPython/Swift比較が成功した。

**アプリCI成功:** [run 39453148802](https://github.com/KANABUNN/RailVelo/actions/runs/39453148802)、対象commit `8808fdd9f4bccf9122b7dceedfac99b60285a0eb`。`macos-26` arm64、Xcode 26.6（17F113）/ iOS 26.5 SDK、iPhone 16 Simulator runtime 26.5。Simulator/端末向け署名なしビルド、built Info.plist/同梱リソースの検査、合成リプレイDB（5観測・有効速度5件・matched3件）、終了後の中断復旧が成功した。Swift/Python試験は上記engine CIで行い、アプリCIでは重複実行しない。

ライト/ダークはAppKitで取得した実画像の背景3点を検査し、平均輝度light `0.9648208419481913`（条件: 0.7超）/ dark `0.0`（条件: 0.3未満）で合格。取得画像を目視して切替を確認し、速度71.7 km/h、鹿児島本線・博多方面・駅間進捗の表示を確認した。いずれも合成GPSである。グラフは下へのスクロールが必要なため今回の画像に含まれず、グラフ目視・UI全操作・VoiceOverは未検証。Simulatorの成功を実GPS・実機・実走の合格へ拡張しない。

engineは`macos-15-intel`、アプリは`macos-26`の標準runnerを使う。関連pathの変更時だけ自動実行し、ブランチ単位のconcurrencyで旧実行を取り消す。利用者の明示許可を得た合成リプレイ失敗時の画面・件数診断は1日保持のartifactへ出力し、実GPSや個人データを含めない。

過去試行ではprivate実行のアカウント制約、Network/type guardのコンパイル、pkg-config経由のホストdylib参照、Simulatorの待機・scene設定、ダーク画像の反映待ちを修正した。[前段のrun 39450278021](https://github.com/KANABUNN/RailVelo/actions/runs/39450278021) もDB・中断復旧まで成功したが、画像が両方lightだったため最終確認には使わず、上記runで画像の輝度検査と目視を追加して成功を確認した。

Apple Developer Program登録済みという利用者の回答に加え、有効な会員資格と契約同意済みの状態を画面で読み取り確認した。Explicit App ID `jp.kb-dev.railvelo`（Description: RailVelo）と、App Store Connectアプリ「RailVelo」（アプリID `6824978233`、主言語: 日本語、SKU: `railvelo-ios`、同じBundle ID）の登録完了を画面で確認した。

内部グループ「本人検証」を作成し、自動配信オフ・テスター0人・ビルド0件・公開リンクなしを確認した。招待、証明書/APIキーの生成、署名、アップロードは実施していない。対象buildのグループ割当、Apple処理完了、TestFlight導入と実機受入は未完了。個人情報を除いた画面証跡はリポジトリ外に保存し、本人のアカウント情報・Team ID・秘密鍵は記録しない。[導入手順](APPLE_SETUP.md)

公開前監査では初期の全1 commit・157 blobとSQLite 2個を確認した。既知の秘密鍵・トークン・APIキー等のパターンに該当する機密は検出されなかった。旧SQLiteの`rides`、`gps_samples`、`match_results`、`station_events`は全て0行で、同梱fixtureは固定seedの合成GPS。原典5ファイルのSHA-256は取得記録と一致した。公式CC HTMLには原典の公開連絡先が含まれる。

初期Git履歴のauthor情報とログのユーザー名入りローカルパスを整理した。GitHub上で旧commitを直接参照できる問題を避けるため、既存リポジトリをprivateの退避先へ移し、新しい`RailVelo`へ整理済み履歴を反映した。新リポジトリはclean root commit `2e238881f4a3428eec79a51e03f8ce178db75408`から始まり、旧commitをこのリポジトリからfetchできないことを確認した。その後のアプリソース反映と利用者による公開設定が完了している。検出なしはパターン検査と内容確認を行った範囲の結果であり、将来追加する実走CSVや署名資料まで安全と認定するものではない。

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

SwiftはmacOS/Xcodeで `swift test --package-path swift` と `.github/workflows/swift.yml` のSimulator・全共通データ比較を再実行できる。上記のengine CIでは29試験・17 fixture比較・ライブラリビルドが成功している。アプリは `.github/workflows/ios.yml` または [Apple手順](APPLE_SETUP.md) の署名なしビルド手順で確認する。上記アプリCIでは両ビルド・起動リプレイ・DB・中断復旧・ライト/ダーク画像確認が成功している。

## 次工程の条件

v0.3の `SWIFTUI_HANDOFF.md` を継承し、アプリの実装設計は [v0.4技術設計](TECHNICAL_DESIGN_v0.4.md) に記録した。自動試験・アプリビルド・Simulatorの限定したリプレイ検証は成功済み。残るグラフ目視・UI操作・VoiceOver、署名とTestFlight導入を行い、[実機試験計画](DEVICE_TEST_PLAN.md) に従って権限・前面GPS・欠測・背景・OS終了・保存・CSV・電池・実走を評価する。

現地ではイベント閾値、信号待ちと停車の識別、折尾の駅線形、並走・分岐、トンネル復帰、端末性能を確認する。v0.1/v0.2設計書本文は未取得の制約を維持する。アプリソースを作成した段階と、iPhoneでの受入完了を分けて扱う。
