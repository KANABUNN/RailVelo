# Windowsからのビルド・Apple設定・iPhone 16導入

更新日: 2026-10-21。対象: 個人用RailVelo、iPhone 16、内部TestFlight配布。

Apple Developer Programは利用者から登録済みと回答されている。本アプリのApple側の実際の登録・署名・配布状態とビルド結果は [検証記録](VALIDATION.md) と [作業記録](WORK_LOG.md) に記録する。本書の手順が存在することだけでは、それらを実施済みと扱わない。

## 1. 作業の区切り

| 段階 | 確認できること | 必要な環境・操作 |
| --- | --- | --- |
| Windowsで編集・Python試験 | 参照エンジン、データ整合性、ソース構成 | 現在の作業環境 |
| macOSでSwift試験・署名なしビルド | Swiftコンパイル、ライブラリ試験、Simulator/端末向けリンク | Xcode、GitHub Actionsまたは利用者のMac |
| Simulator起動 | リプレイ画面・一部操作 | macOS、Simulator |
| 署名・Appleへのアップロード | 配布可能なアーカイブ、Appleでの処理 | 本アプリのApp ID、証明書と秘密鍵、プロファイル、App Store Connect |
| 内部TestFlight導入 | 本人のiPhoneへのインストールと起動 | 本人のApple Account、TestFlight |
| 実走受入 | GPS、背景継続、線路推定、消費電力 | iPhone 16と実際の乗車 |

署名なしビルドの成果物は、そのままiPhoneへインストールする配布物にはならない。以降の段階ごとに結果を残す。

## 2. OS・Xcode・費用

アプリの最小対応OSはiOS 16.0。Swift Chartsなど利用APIの下限に合わせる。iPhone 16では端末が対応する搭載OSを使用し、試験時のOSの版とビルド番号を記録する。AppleはiPhone 16を現在のiOS対応端末に含めている。[Appleの対応端末一覧](https://www.apple.com/os/ios/)

App Store Connectへのアップロードは2026-04-28以降、iOS 26 SDK以降でのビルドが必要。最小対応OSとビルド用SDKは別の設定である。アップロード時は正式版Xcodeの採用版、`xcodebuild -version`、`xcodebuild -showsdks`を記録し、Appleの当日の条件に合うことを確認する。[Apple SDK要件](https://developer.apple.com/news/?id=ueeok6yw)、[Xcode・SDK対応表](https://developer.apple.com/xcode/system-requirements)

publicリポジトリでは標準GitHub-hosted runnerの実行は無料。公開設定は利用者が、ソース・データ・履歴に秘密や個人情報がないか確認した上で変更する。大型runnerには別料金がある。[GitHubの無料利用条件](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

privateのまま実行する場合はアカウントの含有枠を消費し、超過は有料。2026-10-20確認の標準macOSランナーの超過単価は **US$0.062/分**、10分ならUS$0.62、30分ならUS$1.86の目安。ジョブごとに分単位へ切り上げられ、成果物保存の超過料金は別途。無料枠の残量、支払設定、予算を確認し、有料利用が必要なら用途・上限を示して利用者の判断を得る。自動実行の頻度と保存期間も確認する。既に所有するMacのXcodeで実行する方法が代替になる。[GitHub料金表](https://docs.github.com/en/billing/reference/actions-runner-pricing)、[含有枠と保存料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## 3. Windowsでの確認

リポジトリのルートで実行する。

```powershell
python -m unittest discover -s tests -v
python scripts/evaluate.py
python scripts/replay.py data/railway.sqlite fixtures/corridor_full.jsonl --output replay.jsonl
```

実走GPS、生成したCSV、Apple認証情報はリポジトリへ追加しない。`.gitignore`で除外されていることと、追加対象の差分を確認する。線路データの出典は [データ出典](data-provenance.md) に記録している。

## 4. macOSでの署名なし検証

CIの定義は `.github/workflows/`、Xcodeプロジェクトは `ios/RailVelo.xcodeproj`、共有schemeは `RailVelo`。同梱のローカルSwift Package以外のアプリ用外部ライブラリは不要。

```sh
swift test --package-path swift
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS Simulator' -derivedDataPath artifacts/DerivedData CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS' -derivedDataPath artifacts/DeviceBuild CODE_SIGNING_ALLOWED=NO build
```

全シナリオのPython/Swift比較も既存のエンジンCIで行う。Simulatorのリプレイでは実際のGPS受信、iPhoneの省電力制御、電池消費は評価できない。失敗時は実行したcommit、Xcode、失敗したコマンドと診断を保存し、修正後に再実行する。

## 5. 本アプリのApple登録

操作対象が正しいTeamであることを利用者が確認する。Apple Accountへのログイン、2要素認証、契約への同意は利用者が行う。パスワード、確認コード、秘密鍵をチャットやレポートへ記載しない。

1. [Developer Account](https://developer.apple.com/account/)に入り、会員資格・契約の有効性、Teamを確認する。
2. Certificates, Identifiers & Profiles → Identifiers → ＋ → App IDs → Appで、Explicit App IDを登録する。プロジェクトの初期Bundle IDは `jp.kb-dev.railvelo`。登録の可否と利用者の管理する命名に合わせ、変更する場合はXcode設定・配布設定も同時に更新する。登録済みとは推測しない。[App ID登録](https://developer.apple.com/jp/help/account/identifiers/register-an-app-id)
3. [App Store Connect](https://appstoreconnect.apple.com/) → Apps → ＋ → New AppでiOSアプリを作成する。名称、主言語、同じBundle ID、利用者が管理するSKUを指定する。App Store ConnectのアプリIDは生成後に記録する。
4. この実装の背景位置情報はXcodeのBackground Modes / Location updatesと用途説明で設定する。不要なPush Notifications、CloudKit、Sign in with Appleなどは有効化しない。
5. 登録したTeamとBundle IDが、署名対象アプリおよびプロファイルに一致することを確認する。

## 6. 署名資料の準備

### Macを利用できる場合

Xcode Settings → Accountsへ本人がログインし、対象Teamで署名を管理する。証明書を作成する必要がある場合は、既存証明書の用途と有効期限を先に確認する。既存アプリ用の証明書を不用意に失効させない。秘密鍵を伴う証明書の書き出しは利用者が安全な保管先へ行う。[署名証明書の管理](https://help.apple.com/xcode/mac/current/en.lproj/dev154b28f09.html)

### Windows中心でCI署名する場合

手動署名では、安全な環境で鍵とCSRを作成し、Apple Distribution証明書を発行、対応する秘密鍵と証明書をPKCS#12へまとめる。CSR作成から秘密鍵の保管までを同じ管理範囲で扱う。Apple公式のMacでのCSR作成手順も利用できる。[CSR作成](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request)

Certificates, Identifiers & Profiles → Profiles → ＋ → App Store Connectを選択し、今回のExplicit App IDとDistribution証明書を指定してプロファイルを生成する。TestFlight用にiPhoneのUDIDをプロファイルへ登録する工程はない。Xcodeの自動署名を選んだ場合はXcodeがプロファイルを管理する。[配布プロファイル](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile)

GitHubに置く場合は、`.p12`、そのパスワード、`.mobileprovision`、API秘密鍵をGitHub Actions Secretsへ本人が登録する。Base64化だけでは暗号化にならない。秘密鍵の内容、復号後ファイル、keychainを成果物に含めない。CI署名処理は一時keychainを作り、後処理を成功・失敗の両方で実行する。署名用の別workflowを構成・レビューしてから使用する。

## 7. App Store Connect APIの利用

APIキーは自動アップロードを採用する場合に用意する。Account HolderがUsers and Access → IntegrationsでAPIアクセスを申請し、承認状態を確認する。Team keyは権限によってアカウント内の複数アプリへ影響する。必要な操作に合う最小限の権限を選ぶ。Individual keyはProvisioning APIを利用できないため、証明書・プロファイルまで自動化する設計ではキーの種別を確認する。[APIの開始手順](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api)、[APIキーの種類](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)

`.p8`のダウンロードは一度のみ。本人が安全に保管し、CIを使う場合はSecretsへ設定する。Key ID・Issuer ID・秘密鍵の用途を混同せず、アプリ本体へ埋め込まない。APIキーはDistribution証明書の秘密鍵を代替しない。今回のアプリはAPNsを使わないのでAPNsキーの発行は不要。

## 8. 内部TestFlightへ配布

1. 署名付きArchiveを作成する。Bundle ID、Team、version/build番号、組み込まれたプロファイル、SDKを確認する。
2. Xcode Organizerまたは承認したCIでApp Store Connectへアップロードする。個人配布では内部限定を選べる場合にTestFlight Internal Onlyを使用する。
3. App Store Connectで処理の完了・利用可能状態を確認する。APIを使う場合はprocessing stateが`VALID`であることを確認する。暗号化・輸出コンプライアンスの質問は実装に照らして利用者が回答する。
4. TestFlight → Internal Testingで本人用グループを作成し、本人のApp Store Connectユーザーと対象buildのみを追加する。他人への招待は別途明示された場合に行う。公開リンクや外部テスターは作らない。
5. 内部テスター数・対象build・内部テスト可能状態を画面またはAPIで確認する。内部テスターは最大100人のApp Store Connectユーザーで、buildの試験可能期間は90日。[内部テスターの追加](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers)
6. 本人のiPhone 16でTestFlightをインストールし、同じApple Accountで招待を受け、対象version/buildを導入する。アプリ起動と設定画面の版を照合する。[TestFlightの流れ](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)

アップロード成功、Appleでの処理完了、グループ割当、本人端末へのインストール、実GPS動作をそれぞれ独立に記録する。証跡へ本人のメールアドレスやTeamの秘密情報を転記しない。

### Ad Hocを選ぶ場合

Ad Hocは対象iPhoneのUDID登録、Distribution証明書、端末を含むプロファイル、署名付き配布物と導入経路が必要。Windows中心の個人試験ではTestFlightの方が端末配布を進めやすい。Ad Hocを選んだ場合はUDIDを公開リポジトリやログへ載せない。[Ad Hocプロファイル](https://developer.apple.com/help/account/provisioning-profiles/create-an-ad-hoc-provisioning-profile/)

## 9. 位置情報と個人情報

アプリを前面で開いてから実GPS記録を開始し、用途説明を読んで位置情報を許可する。正確な位置情報を無効にした場合や拒否した場合の表示は [実機試験計画](DEVICE_TEST_PLAN.md) で確認する。Core Locationの許可はGPSを毎秒取得できる保証にはならない。

背景継続は`UIBackgroundModes=location`と`allowsBackgroundLocationUpdates`を記録中に使う構成。画面ロック・他アプリ移動・OS終了・強制終了は条件が違う。標準位置更新はアプリ終了で停止するので、自動再起動による無欠測記録を保証しない。[背景更新設定](https://developer.apple.com/documentation/corelocation/cllocationmanager/allowsbackgroundlocationupdates)、[標準位置更新の終了条件](https://developer.apple.com/documentation/CoreLocation/CLLocationManager/startUpdatingLocation%28%29?language=objc)

GPS履歴は端末内に保存し、利用者がCSV共有操作を行った場合に選択先へ渡す。CSVは移動時刻・位置を含む個人データなので、公開の試験証跡へ添付しない。OSのバックアップ・共有先の扱いも端末設定と実装で確認する。App Store公開へ進む場合はプライバシーポリシーURLと実際の収集状況を申告する。Appleの定義では端末内のみで処理するデータは収集に該当しないが、将来の送信・解析SDK追加時は再評価する。[プライバシー設定](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/)、[収集の定義](https://developer.apple.com/app-store/app-privacy-details/)

## 10. 再開時の確認票

- 対象Git commit、Xcode、SDK、成功したビルド・試験のURLを記録した。
- Appleの対象Team、Bundle ID、App Store ConnectアプリIDを確認した。
- 証明書とプロファイルの有効期限、秘密鍵の保管場所を本人が把握している。
- API・CI・課金の使用範囲が決まり、必要な設定を本人が完了した。
- TestFlightの対象build、本人グループ、テスター数、公開リンクなしを確認した。
- iPhone 16での導入・前面GPS・背景・履歴・CSV・実走の結果を分けて記録した。

未完了の行は [作業記録](WORK_LOG.md) に残し、次回その段階から再開する。
