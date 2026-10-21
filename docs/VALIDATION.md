# 実行確認と受入範囲 — v0.5 内部配布・実GPS基本動作を確認

## 最新状態（2026-10-21）

**TestFlightの本人限定配布が成功し、iPhone 16への導入・起動と実GPSの基本動作を本人申告で確認した。最優先の「TestFlight経由で導入し、実GPSの基本動作を確認する」条件へ到達した。約5分のロック中のグラフ上の記録継続も確認したが、10分以上の背景試験・長時間・列車での実走評価は未完了として残す。**

| 項目 | 結果・証跡 |
| --- | --- |
| 配布アプリ | RailVelo `0.5.0 (500.7.1)` / `jp.kb-dev.railvelo` / ASC `6824978233` |
| アプリsource | `afd55bb73ac919feed936a943899da115a6cd2b5`。engine/app CIが同じSHAで成功 |
| 配布control | `1ac3489cac9029ae8a63e62125eed75f1248d98b` |
| 実配布CI | [run 39536734020](https://github.com/KANABUNN/RailVelo/actions/runs/39536734020)、署名job `119015035914` がsuccess。Xcode 26.6 |
| Archive・署名検査 | 成功。Bundle ID・版・埋め込みprofile・strict codesign・entitlements・署名leaf証明書を照合 |
| Apple処理 | 実アップロード成功、読み取りAPIで対象buildの`VALID`・`INTERNAL_ONLY`・未期限切れを確認 |
| 本人への割当 | 「本人検証」内部グループ、本人1人・当該build1件・招待済み。Xcodeビルドを手動配信。外部テスター・公開リンクは追加していない |
| 後処理 | `cleanup_ok=true`。元keychain/profileを復元し、一時署名資料と生ログを削除 |
| 成功JSON | [検証済みsafe-status](evidence/testflight-500.7.1.json)。artifact `12317731962`、ZIP SHA-256 `f3cafd3e19734ddab0900478bd163fce179332ded7df045c91452eacb0561fa0` |
| iPhone導入 | iPhone 16 / iOS 27.0.1、案内したbuildのインストール・起動成功を本人が回答。直接端末を観測した結果ではない |
| 実GPSの基本表示 | GPS精度、静止・歩行時の速度、グラフの表示を確認したと本人が回答。数値や定量的な正確さは未報告 |
| CSV保存 | 保存できたと本人が回答。保存先、ファイルの再読込・内容・列形式は未確認 |
| 画面エラー | 今回の試験中、画面上にエラーは出ていないと本人が回答。内部診断ログは未取得 |
| 位置情報設定 | 後続のロック試験で「常に許可」「正確な位置情報オン」と本人が回答 |
| 約5分の画面ロック | ロック中もグラフ上に記録が続き、解除後の画面表示・CSV保存に問題なく、画面エラーなしと本人が回答。10分以上・新規GPS更新・取得間隔・欠測の解析は未確認 |

safe-statusの`testers_modified=false`はCIがテスター追加を行わないことを表す。本人への招待とグループ割当はCI成功後、承認済みの別の画面操作として実施した。`device_acceptance=not_verified`もCI時点の記録であり、その後の導入・起動と実GPS基本試験の本人申告は上表へ別に記録した。画面の「テスト中」は配布可能状態であり、実機GPSの合格とは区別する。本人のメール、Team/Profile/API識別子、秘密鍵、実GPS座標は公開記録へ含めない。

### 実GPS基本試験の確認範囲

2026-10-21、利用者は案内した静止・歩行の前面試験に対し、GPS精度、静止・歩行速度、グラフの表示を確認し、CSVへ保存でき、画面上にエラーは出ていないと回答した。対象は案内したRailVelo `0.5.0 (500.7.1)` / iPhone 16 / iOS 27.0.1。ツールによる端末の直接観測やCSV解析ではなく、この本人申告を証跡とする。基本動作の確認であり、速度・位置の精度や全実機試験の合格を示すものではない。

測位までの秒数、静止・歩行の実数値、最高速度、グラフを見た画面・期間・連続線、履歴の再起動後の保持、CSVの内容・再読込は未回答である。位置情報の設定は後続のロック試験で本人申告を得た。実測値や位置情報を推測で補わない。

### 約5分の画面ロック試験

2026-10-21、同じ対象版で、位置情報は「常に許可」、正確な位置情報はオン、ロック時間は約5分で、ロック中もグラフ上に記録され続け、CSV保存に問題なく画面上のエラーもないと本人が回答した。解除後の画面が正しく表示されることも確認した。端末の直接観測やCSV解析は行っていない。

これは約5分の短期条件での確認であり、[B01](DEVICE_TEST_PLAN.md)の10分以上という条件には達していない。グラフ上の記録継続を、無欠測・一定の取得間隔・連続線の確認とは扱わない。解除後の画面表示と、新しいGPS観測による値の更新も区別し、後者は未確認。別アプリを約10分使う試験は依頼済みで、結果待ち。

最終アプリ候補の[engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39531707938)はPython76件・Swift32件・17 fixture比較・Swift生成CSVのPython解析・iOSライブラリが成功。[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39531634651)も両署名なしビルド・smoke/中断復旧・3件のUI試験に成功した。速度グラフ3期間の点描画、記録操作、履歴/対象削除、ネイティブCSV共有画面、明暗・大きい文字を実画像で確認した。[Simulator詳細](SIMULATOR_UI_VALIDATION.md)

配布controlのオフライン境界49件、全Python101件は暗号依存ありのbundled Pythonでskipなし成功し、独立レビューも通過した。実Archive・署名検査・送信・Apple処理の成功は上記実配布runで別に確認した。

実GPSの連続線・定量精度、実際のVoiceOver、10分以上のロック/他アプリ中の記録と欠測、復帰後の新しいGPS値の更新、実機での中断復旧、履歴再読込、CSVの内容・再読込、長時間・電池・CPU/メモリ、列車での実走評価は未検証。実走ログ未取得のため、合成値から実走精度を確定していない。[実機計画](DEVICE_TEST_PLAN.md)と[非公開ログ解析](RIDE_EVALUATION.md)で続行する。

## v0.5の検証・修正経過（当時の状態）

以下の未確認・停止・次回実行という記述は、その試行時点の記録。現在の配布・導入状態は上表を正とする。


UUID修正後の[run 39536001985](https://github.com/KANABUNN/RailVelo/actions/runs/39536001985)は`0.5.0 (500.6.1)`の署名付きArchive生成が成功し、Bundle ID・version/build・埋め込みprofileの照合を通過した。その後の`verify`でinput file missing / 終了コード1となり、upload前に停止した。safe-status ZIPのSHA-256は`430aafa10cf5d4e25f682cd3e862c9bfa8a259d01e2293444c780c3db1b3a454`、cleanup成功を確認した。Archive失敗ではないため、暗号化ログartifactは生成されていない。証明書抽出のoptional引数を`--extract-certificates=<prefix>`の1引数へ修正した。現証跡ではverify内のどの呼出しが失敗したかは未確定のため、署名・entitlements・証明書検査の固定subphaseも追加し、回帰試験と独立レビューに成功した。[Appleの指定例](https://developer.apple.com/cn/documentation/devicemanagement/allowing-and-denying-apps-and-binaries)

[run 39535387592](https://github.com/KANABUNN/RailVelo/actions/runs/39535387592)の承認済み暗号化Archive診断を取得し、artifact SHA-256 `a26fd198f5915966e87899c3fa0b612158bb5a5af05b6be4b18289242136eccc`と期待source/build/run/attemptを照合して、本人PCの非公開領域へ復号した。Xcodeは指定profileを見つけられていなかった。Apple profileのUUIDは小文字だがhelperが大文字へ変換しており、CLIとエラーの識別子は元のUUIDと表記だけが不一致だった。UUIDの構文検査を維持しながら元の表記を保持し、profile配置・Archive・export・cleanupへ一貫して渡す修正を行い、回帰試験と独立レビューに成功した。実Archiveで解消するかは再実行で確認する。プロファイルや証明書の再発行、信頼設定、アプリソースは変更しない。値・ログ本文は公開しない。

[run 39534452207](https://github.com/KANABUNN/RailVelo/actions/runs/39534452207)は`500.4.1`のArchiveで同じ終了コード65となり、固定診断は未分類2件で原因未確定。暗号化した失敗Archive出力の一時保存を利用者が個別承認した。新しい本人PC用の復号鍵はWindows DPAPIと限定ACLで保護し、公開鍵だけをリポジトリへ追加する。単一Archiveの暗号化・合成データの復号往復・改ざん拒否・既定オフ・スコープ検査を実試験し、独立レビューを通過した。まだ実ログの回収・原因特定・署名付きArchive成功を確認したものではない。

配布診断の追加後、オフライン境界試験49件・全Python101件（暗号依存を含むbundled Python、skipなし）がローカルで成功した。公開状態JSONはschema 2へ更新し、固定ラベルの複数タグ、厳格な既知コマンド名、未分類エラー行の数だけを追加した。原文・path・アカウント・証明書情報は含めない。独立レビューでも公開範囲・非出力・通常の進捗を誤認しないことを確認した。署名設定とアプリソースは変更していない。

**最終配布候補:** `afd55bb73ac919feed936a943899da115a6cd2b5`。[engine run 39531707938](https://github.com/KANABUNN/RailVelo/actions/runs/39531707938)はPython76件・Swift32件・17 fixture比較・Swift CSV相互運用・iOSライブラリが成功。[app run 39531634651](https://github.com/KANABUNN/RailVelo/actions/runs/39531634651)もSimulator/端末向け署名なしビルド、smoke/中断復旧、3件のUI試験が成功した。グラフ3期間・拡大文字・Darkの実画像で時刻目盛の重なり解消を確認した。[UI検証証跡](SIMULATOR_UI_VALIDATION.md)

同じsourceを指定した[内部配布run 39532617433](https://github.com/KANABUNN/RailVelo/actions/runs/39532617433)を手動起動した。gateとXcode ExportOptions確認、署名資料検査、実Apple API認証・アプリ照合、keychain導入まで成功したが、`0.5.0 (500.2.1)`のArchive作成で停止した。固定分類を強化した[run 39533409609](https://github.com/KANABUNN/RailVelo/actions/runs/39533409609)も`500.3.1`のArchive段階で停止し、終了コード65、分類unknownで原因は未確定。両runのsafe-status JSONをハッシュ照合して取得し、`phase=archive`、`upload_completed=false`、`cleanup_ok=true`を確認した。Appleへのアップロードは実行されていない。run3のartifact SHA-256は`cdaf4c72bc3f7cb371ffd9477742b6c7bfc2255abfc7dac7767dc8506ca7daf1`。26件の配布境界試験を含むPython78件がローカルで成功した。

**engine CI成功:** [run 39530105805](https://github.com/KANABUNN/RailVelo/actions/runs/39530105805)、対象commit `52464c9f58d1b2435a425a32dad7c6251699e066`。Python76件、Swift32件（Core/SQLite12＋Recording20）、Swift生成の実39列人工CSV→Python解析、17 fixture比較、iOS向けライブラリが成功した。同commitの[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39529981900)でも両ビルド・smoke・中断復旧、Light全操作/LargeText、Dark監査/スクロールの各stepが成功した。グラフの時刻ラベル短縮を追加修正し、上記最終版で再試験した。[UI詳細](SIMULATOR_UI_VALIDATION.md)

先行する`512ea03`の[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39528724495)は、大きい文字の監査、3期間グラフ、一時停止・履歴保護・再開まで成功したが、終了確認の親子Button重複とDarkの細い駅間進捗領域で失敗した。確認ボタンを明示IDで操作し、進捗を割合・次駅距離を含む高さ44pt以上の1要素へ修正し、上記で再試験した。Light/Darkの実画面添付の書き出しは成功した。

先行するcommit `3619ecc`の[アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39526756727)は両ビルド・既存smoke・修正済み中断復旧まで成功した。新規UI試験はグラフ3期間の描画まで通ったが、大きい文字の速度表示と履歴スワイプ後の画面遷移で失敗した。速度文字へDynamic Type対応を追加し、リプレイを早めに一時停止して履歴画面を確認する手順へ修正した。UI全操作は上記最終版で合格した。配布・実機の受入は別に確認する。

既存v0.4の成功結果を下に保存する。v0.5では実リプレイを使用したXCUITest（グラフ描画・3期間切替・スクロール・記録操作・履歴/削除・CSV共有画面・大きい文字/明暗Accessibility Audit）を追加し、最終候補のCIで成功した。VoiceOverの実際の読み上げ、TestFlight配布、iPhone 16の実GPS・背景・電池、実走評価は未実施。

実走ログは既存CSVの先頭36列を維持し、受信時刻・保存処理開始時刻・診断JSONを末尾へ追加した39列へ拡張した。GPSエラー、権限、アプリ状態を端末内に記録する。保存処理開始までの経過はSQL/commit時間やCPU使用率ではない。個人の位置情報を含むファイルは`recordings/`に保存し、公開CIでは人工データだけを使う。[実走解析と記録様式](RIDE_EVALUATION.md)

署名付き配布は手動起動・内部テスト限定のワークフローを作成済み。利用者の明示許可を得て新しいDistribution証明書と生成鍵の一致、専用App Store profileの対象・期限・証明書一致、API鍵形式を実ファイルで確認した。GitHubはmainのみ・本人reviewer必須・admin bypass無効のEnvironmentに7 Secretsを登録済み。秘密値は記録しない。登録中だけの一時的な読取権限は別途明示許可を得て設定し、登録後に削除・確認した。Apple API認証は成功し、署名付きArchive・アップロード成功・処理完了・本人グループへの割当・実機導入はまだ未確認。

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
