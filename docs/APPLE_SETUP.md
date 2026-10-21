# Windowsからのビルド・Apple設定・iPhone 16導入

更新日: 2026-10-21。対象: 個人用RailVelo、iPhone 16、内部TestFlight配布。

Apple Developer Programの有効な会員資格・契約同意済み状態、Explicit App ID `jp.kb-dev.railvelo`、App Store Connectアプリ「RailVelo」（ID `6824978233`）の登録完了を画面で確認済み。内部グループ「本人検証」は作成済みで、自動配信オフ・テスター0人・ビルド0件・公開リンクなし。利用者承認後、新しいDistribution証明書/p12・専用プロファイル・Developer Team APIキーを生成し、保護した配布Environmentへ7種類のSecretsを登録済み。実署名・API認証・アップロード・本人追加・実機導入は未実施。本アプリの実際の登録・署名・配布状態とビルド結果は [検証記録](VALIDATION.md) と [作業記録](WORK_LOG.md) に記録する。

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

publicリポジトリでは標準GitHub-hosted runnerの実行は無料。本リポジトリは公開前点検と履歴整理の後、利用者による公開設定をGitHubのリポジトリ情報で確認した。大型runnerには別料金がある。[GitHubの無料利用条件](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

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

[engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39447558500) はcommit `e206e23aacaaf9dcc298c54557808fda13ce40ba`で成功。Xcode 16.4 / iOS Simulator 18.5 SDKを用い、Python36件、Swift29件、17 fixture比較、Core Location/SQLiteのiOS Simulator向けライブラリビルドに成功した。

[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39453148802) はcommit `8808fdd`、`macos-26`（arm64）、Xcode 26.6（17F113）/ iOS 26.5 SDK、iPhone 16 Simulator runtime 26.5で成功。Simulator/端末向け署名なしビルド、built Info.plist/同梱リソース、リプレイDB（5観測・有効速度5件・matched3件）、中断復旧、ライト/ダーク表示を確認した。表示は背景輝度の自動検査と画像の目視で確認したが、グラフ目視・UI全操作・VoiceOverは未検証である。

v0.5のsource `083e`では[engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39524933942)がPython52件・Swift32件・interop・17 fixture比較に成功した。アプリCIの署名なし2ビルドとsmokeも成功したが、復旧試験はfixtureの自然終了で前提を満たさず失敗した。試験前提は修正済みで、次commitの再実行待ち。上記v0.4の結果と最新sourceの試験結果を区別する。

Swift/Python試験と17 fixture比較は`macos-15-intel`のengine CI、アプリ確認は`macos-26`のアプリCIで実施する。関連pathに絞った自動実行とブランチ単位のconcurrencyを使用する。診断は利用者の明示許可を得た合成リプレイの失敗画面・件数に限定し、artifactを1日保持する。署名・TestFlight・実機導入・実GPS・背景・電池・実走は未検証。結果は [検証記録](VALIDATION.md) に記録する。

```sh
swift test --package-path swift
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS Simulator' -derivedDataPath artifacts/DerivedData CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/RailVelo.xcodeproj -scheme RailVelo -destination 'generic/platform=iOS' -derivedDataPath artifacts/DeviceBuild CODE_SIGNING_ALLOWED=NO build
```

全シナリオのPython/Swift比較も既存のエンジンCIで行う。Simulatorのリプレイでは実際のGPS受信、iPhoneの省電力制御、電池消費は評価できない。失敗時は実行したcommit、Xcode、失敗したコマンドと診断を保存し、修正後に再実行する。

## 5. 本アプリのApple登録

操作対象が正しいTeamであることを利用者が確認する。Apple Accountへのログイン、2要素認証、契約への同意は利用者が行う。パスワード、確認コード、秘密鍵をチャットやレポートへ記載しない。

1. [Developer Account](https://developer.apple.com/account/)に入り、会員資格・契約の有効性、Teamを確認する。
2. Certificates, Identifiers & Profiles → Identifiersで、今回のExplicit App ID `jp.kb-dev.railvelo`（Description: RailVelo）の登録完了を確認済み。今後Bundle IDを変更する場合は対象を登録し直し、Xcode設定・配布設定も同時に更新する。[App ID登録](https://developer.apple.com/jp/help/account/identifiers/register-an-app-id)
3. [App Store Connect](https://appstoreconnect.apple.com/)のiOSアプリ「RailVelo」を作成済み。アプリID `6824978233`、主言語は日本語、SKUは`railvelo-ios`、Bundle IDは`jp.kb-dev.railvelo`である。新規アプリの作成画面で重複登録せず、今回のアプリを開いて以降の設定を行う。
4. この実装の背景位置情報はXcodeのBackground Modes / Location updatesと用途説明で設定する。不要なPush Notifications、CloudKit、Sign in with Appleなどは有効化しない。
5. 登録したTeamとBundle IDが、署名対象アプリおよびプロファイルに一致することを確認する。

## 6. 署名資料の準備

### Macを利用できる場合

Xcode Settings → Accountsへ本人がログインし、対象Teamで署名を管理する。証明書を作成する必要がある場合は、既存証明書の用途と有効期限を先に確認する。既存アプリ用の証明書を不用意に失効させない。秘密鍵を伴う証明書の書き出しは利用者が安全な保管先へ行う。[署名証明書の管理](https://help.apple.com/xcode/mac/current/en.lproj/dev154b28f09.html)

### Windows中心でCI署名する場合

手動署名では、安全な環境で鍵とCSRを作成し、Apple Distribution証明書を発行、対応する秘密鍵と証明書をPKCS#12へまとめる。CSR作成から秘密鍵の保管までを同じ管理範囲で扱う。Apple公式のMacでのCSR作成手順も利用できる。[CSR作成](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request)

Certificates, Identifiers & Profiles → Profiles → ＋ → App Store Connectを選択し、今回のExplicit App IDとDistribution証明書を指定してプロファイルを生成する。TestFlight用にiPhoneのUDIDをプロファイルへ登録する工程はない。Xcodeの自動署名を選んだ場合はXcodeがプロファイルを管理する。[配布プロファイル](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile)

GitHubに置く場合は、`.p12`、そのパスワード、`.mobileprovision`、API秘密鍵を承認した配布用EnvironmentのSecretsへ登録する。Base64化だけでは暗号化にならない。秘密鍵の内容、復号後ファイル、keychainを成果物に含めない。署名用workflowの下書きは作成済みで、実行前の利用者確認と保護設定は [v0.5の確認事項](#v05-distribution-status) に従う。

## 7. App Store Connect APIの利用

APIキーは自動アップロードを採用する場合に用意する。Account HolderがUsers and Access → IntegrationsでAPIアクセスを申請し、承認状態を確認する。Team keyは権限によってアカウント内の複数アプリへ影響する。必要な操作に合う最小限の権限を選ぶ。Individual keyはProvisioning APIを利用できないため、証明書・プロファイルまで自動化する設計ではキーの種別を確認する。[APIの開始手順](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api)、[APIキーの種類](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)

`.p8`のダウンロードは一度のみ。本人が安全に保管し、CIを使う場合はSecretsへ設定する。Key ID・Issuer ID・秘密鍵の用途を混同せず、アプリ本体へ埋め込まない。APIキーはDistribution証明書の秘密鍵を代替しない。今回のアプリはAPNsを使わないのでAPNsキーの発行は不要。

## 8. 内部TestFlightへ配布

1. 署名付きArchiveを作成する。Bundle ID、Team、version/build番号、組み込まれたプロファイル、SDKを確認する。
2. Xcode Organizerまたは承認したCIでApp Store Connectへアップロードする。今回の本人用配布はTestFlight Internal Onlyを必須とし、設定を確認できなければ停止する。
3. App Store Connectで処理の完了・利用可能状態を確認する。APIではprocessing stateが`VALID`かつ`buildAudienceType=INTERNAL_ONLY`であることを確認する。暗号化・輸出コンプライアンスの質問は実装に照らして利用者が回答する。
4. TestFlight → Internal Testingのグループ「本人検証」は作成済み。自動配信オフ、テスター0人、ビルド0件、公開リンクなしを確認した。署名・アップロード後、本人のApp Store Connectユーザーと対象buildのみを追加する。他人への招待は別途明示された場合に行う。公開リンクや外部テスターは作らない。
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

<a id="v05-distribution-status"></a>

## 11. v0.5 配布方式・承認と準備状況

以下は2026-10-21にApple/GitHubの一次情報を確認した配布設計と現在の準備結果。利用者は新しい署名資料/APIキーの発行、Secrets保管、本人限定uploadとグループ割当を承認済み。実署名・認証・アップロードは未実施。対象は`jp.kb-dev.railvelo` / App Store Connect `6824978233`、内部グループは「本人検証」で、テスター0人・ビルド0件・自動配信オフ・公開リンクなしである。

### 推奨: 署名とアップロードの権限を分ける

準備前の読み取り確認では、既存Distribution証明書1件、他アプリ向けプロファイル3件、他アプリ名のDeveloper Team APIキー1件が存在した。既存アプリの秘密鍵/p12/APIキーは取得・流用していない。

利用者承認後、**新しいDistribution秘密鍵/CSR・証明書（2027-10-21まで有効）・p12と、RailVelo専用App Store Connectプロファイルを生成済み**。p12の証明書と自前秘密鍵の一致を確認し、新しいDeveloper Team APIキーも発行済み。この構成ではCIに証明書・App ID・プロファイルを自動作成する権限を必須にしない。[GitHubのp12/プロファイル導入手順](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)

Distribution秘密鍵とp12はパスワードで暗号化している。Appleから取得するAPIのp8は平文の鍵形式であり、所有者/SYSTEMだけに限定したACLで保管する。署名資料フォルダー全体にも同じアクセス制限を設定している。登録時の一時的なエージェント読取権限は利用者の明示許可後に追加し、登録後の削除を確認済み。保管先・Team ID・APIキー識別子・秘密値は公開記録へ記載しない。

| 方式 | 必要なもの・権限 | 今回の判断 |
| --- | --- | --- |
| 手動署名＋APIアップロード | Distribution p12、対応プロファイル、アップロード可能なAPI認証 | 初回の推奨。作成・更新する対象を明示しやすい |
| APIを用いる自動署名・cloud signing | Provisioningアクセス、必要に応じてcloud-managed Distributionの追加権限 | 既存の役割・追加権限を確認し、必要性と影響を説明して選択する |
| 本人のMacでXcode Organizer配布 | Mac、本人によるログインと署名設定 | CIへの秘密登録を避けたい場合の代替。Macの利用可否を確認する |

手動署名でもp12はTeamのDistribution証明書であり、秘密鍵そのものがRailVeloだけに制限されるわけではない。今回のプロファイル・workflowの対象をRailVeloに限定する。既存アプリが利用する証明書を失効・交換しない。新規発行が必要な場合は、既存証明書への影響と保管方法を説明して確認を得る。[Appleの配布プロファイル](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile)

### APIキーの最小権限

AppleはDeveloper roleでbuildのアップロードと内部TestFlightを利用できるとしている。CIにApp Manager/Adminを必須とはしない。今回の下書きは新しいDeveloper Teamキーを使う方式で、**DeveloperでもTeamキーは全アプリが範囲となり、RailVeloだけへ制限できない**ことを説明して確認する。既存の別アプリ用キーを取得・共用しない。[Appleの最小権限説明](https://developer.apple.com/videos/play/wwdc2026/8010/)、[アップロードの役割](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/)

Individual keyはユーザーのアプリ範囲・役割を引き継ぐ。既存のDeveloperユーザーがRailVeloだけにアクセスできるなら狭い範囲の候補になるが、Account HolderのIndividual keyは本人の広い権限を継承する。現下書きはIssuer IDを持つTeamキーだけに対応するため、Individualを選ぶ場合は認証実装と試験を変更してから進める。

Individual keyはProvisioning APIを使えない。cloud signingには`CLOUD_MANAGED_APP_DISTRIBUTION`などの追加権限とCertificates, Identifiers & Profilesへのアクセスが関係し、初回の実行で証明書が自動作成される場合がある。自動署名を選ぶ場合はその変更も確認対象とする。[APIキーの制約](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)、[cloud signing権限](https://developer.apple.com/documentation/appstoreconnectapi/userrole)、[cloud-managed証明書](https://developer.apple.com/help/account/certificates/cloud-managed-certificates)

### 実行前に利用者へ確認する4項目

今回の4項目は利用者承認済み。以下は今後対象や範囲を変更する場合にも使う確認票であり、未承認状態を表すものではない。

1. 新しいDistribution秘密鍵/CSR・証明書・p12とRailVelo専用App Store Connectプロファイルの発行。既存証明書は失効せず、秘密鍵の保管場所と不要になった際の削除方針を説明する。
2. 新しいDeveloper Team APIキー（全アプリが範囲）の発行と、GitHubのmain限定・本人承認Environment `railvelo-testflight`への下記7種類のSecrets登録。値はチャット・ソース・公開ログへ書かない。
3. 対象commit・version/buildを固定した、TestFlight Internal Onlyでの署名付きアップロード実行。
4. 「本人検証」へ本人だけを追加し、対象buildを割り当てる操作。招待メールが発生し得ることを含めて確認する。

今後も承認範囲を超える秘密取得・新規発行・失効・権限変更・アップロード・招待は行わない。今回の承認を他アプリの秘密情報利用、外部テスター追加、App Store提出へ拡張しない。

### 配布専用CIの設計案

[配布workflow](../.github/workflows/testflight.yml)と[事前照合](../.github/scripts/testflight_gate.py)、[署名・送信補助](../.github/scripts/testflight_release.py)の下書きを作成済み。手動起動のみ、`KANABUNN/RailVelo`のmainのみ、40桁の対象SHAがmainの祖先であること、同じSHAのengine/app CIが両方成功していることを要求する。GitHub APIは`contents: read`と`actions: read`だけで参照する。Environment `railvelo-testflight`はmainブランチのみ・tag 0件・本人required reviewer・admin bypass無効で設定し、下記7種類のSecrets名を確認済み。保護規則の承認後にのみ署名ジョブがSecretsへアクセスする。[GitHub Environment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

| Environment Secret名 | 用途 |
| --- | --- |
| `RAILVELO_TEAM_ID` | profile/証明書/ArchiveのTeam照合 |
| `DISTRIBUTION_P12_BASE64` | 秘密鍵を含むDistribution署名資料 |
| `DISTRIBUTION_P12_PASSWORD` | p12の復号 |
| `PROVISIONING_PROFILE_BASE64` | RailVelo専用App Store Connectプロファイル |
| `ASC_API_KEY_P8_BASE64` | 新しいDeveloper Team API秘密鍵 |
| `ASC_KEY_ID` | APIキー識別子 |
| `ASC_ISSUER_ID` | Team API認証のIssuer識別子 |

p12・パスワード・プロファイル・API秘密鍵は承認した配布ジョブにだけ渡す。下書きはTeam/Bundle、有効期限、App Store用属性、証明書の一致を照合し、権限制限した一時ファイルと一時keychainを使う。終了時は元のkeychain検索設定・既存profileを復元して一時資料を削除する。証明書名・Team ID・profile UUIDをmaskし、コマンドの生出力は非公開の一時ログだけに保存する。失敗時の公開診断は固定分類（profile/署名/認証/SDK/コンパイル/送信/通信/timeout等）と終了コードだけで、生ログを抜粋しない。公開artifactは許可した項目だけのstatus JSON（1日保存）で、IPA・Archive・profile・生ログを含めない。Base64は保存形式で、暗号化ではない。

オフライン境界試験24件が成功した。ローカルのp12生成と自前鍵の一致は確認したが、CIでの実署名・Apple認証・送信は未実施。復元snapshotは同じ一時領域で完全書込み後に原子的に置き換え、更新中断時も前の復元情報を残す。依存はES256認証とp12/証明書検査用の`PyJWT[crypto]==2.15.1`、`cryptography==50.0.2`に固定し、2026-10-21時点の公式安定版変更履歴を確認した。macos-26 arm64/Xcode 26.6を指定する。[PyJWT変更履歴](https://pyjwt.readthedocs.io/en/stable/changelog.html)、[cryptography変更履歴](https://cryptography.io/en/latest/changelog/)

### 内部限定exportとbuild番号

下書きは署名Archiveの識別子・profile・証明書・entitlementsを検査してから、`method=app-store-connect`、`destination=upload`、`signingStyle=manual`、`testFlightInternalTestingOnly=true`でXcodeから直接送信する。これらの正確なキー・型・methodの対応は **実行に使うXcode 26.6の`xcodebuild -help`で確認するまで未検証** であり、必要項目が存在しなければ停止する。AppleはExportOptionsの一覧を同コマンドで確認するよう案内している。Internal Onlyは内部テスターへ配布し、外部TestFlightやApp Store提出へ使えない配布方法である。[Appleの配布方式](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)、[ExportOptionsの確認方法](https://developer.apple.com/library/archive/technotes/tn2339/_index.html)

現在のプロジェクト設定は`0.5.0 (500.0.1)`。配布workflowは **version `0.5.0` / build `500.<GITHUB_RUN_NUMBER>.<GITHUB_RUN_ATTEMPT>`** へ上書きする。例は`500.12.3`。再実行で変わらないrun番号に増加するattemptを組み合わせ、送信前に同じアプリ・version・buildが存在しないことを確認する。workflow移行や手動配布で採番規則が変わる場合は、既存最大値とAppleの受理を再確認する。[Apple build string](https://developer.apple.com/help/glossary/build-string/)、[GitHub変数](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)

### アップロード後の確認

アップロードの終了コードだけで完了にせず、下書きは読み取りAPIでアプリ・version/buildを照合し、最大20分まで`processingState=VALID`かつ`buildAudienceType=INTERNAL_ONLY`を待つ。関連アプリを`include=preReleaseVersion,app`で明示取得し、アプリIDとBundle IDも照合する。処理失敗・不明属性・期限切れ・確認期限超過は成功にしない。その後、利用に必要な輸出コンプライアンス、本人用グループの対象build、本人テスター、公開リンクなしを画面で確認する。テスター追加・グループ割当は自動化せず、利用者確認後の別操作とする。iPhone導入完了も別に確認し、本人のメールアドレスを公開報告へ含めない。[build処理状態](https://developer.apple.com/documentation/appstoreconnectapi/build/attributes-data.dictionary)、[内部限定属性](https://developer.apple.com/documentation/appstoreconnectapi/buildaudiencetype)、[内部グループ設定](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers)
