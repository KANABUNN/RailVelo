# 作業記録 2026-10-20

以下はv0.3作業終了時点の記録。v0.4の追加作業と現在の状態は後段に追記する。

1. 作業フォルダーが空であることを確認。前工程の保存先を質問し、指定された `railmonitor_n02/output` と親フォルダーを読み取り確認した。
2. 元SQLite、SQL、取得・変換スクリプト、公式ZIP、設定・品質記録を `vendor/n02/` へコピー。指定元ファイルを変更せず、ハッシュを照合した。
3. 元のSQLite検証30項目と接続試験5件を再実行。推定用双方向グラフを生成し、近隣15路線を比較候補として追加した。代表駅間弧長と営業キロの差、接続の未確認事項は維持した。
4. Python HMM前向きフィルター、方向・前後駅・弧長距離、欠測予測、駅イベント、読み取り専用SQLite APIを実装した。
5. Swift Packageの計算、SQLite、Core Location、リプレイCLI、テスト、macOS/iOS CI定義を分離して作成した。
6. 人工分岐・並走ネットワークと実N02全区間の順逆両方向の合成GPSを作成。初回試験で不正入力後の時刻状態と駅端停止の誤到着を検出・修正。継続移動を条件とする発車・再開、駅中心通過後の停車の誤通過抑止、折り返し時の移動履歴保持、徐行を停止時間に含めない処理も追加した。
7. 最終自動テスト・定量評価・SQLite/JSON一致・再現性の結果は `VALIDATION.md`、`evaluation.*`、`data-quality.*` に記録する。

現在の残課題：Swiftの実コンパイル、Python/Swift実行結果比較、iOS SimulatorとiPhone実機、実走GPSでのイベントと位置精度、実際の分岐接続・停止位置の確認。Gitリモートを設定していないためCIは実行していない。有償サービスの作成や外部サービスの設定変更は行っていない。

## v0.4 追加作業（2026-10-21）

利用者の依頼に従いGitリポジトリを作成し、GitHubへ初回反映した。追加回答でアプリ実装・ビルド検証までの継続と、Apple Developer Program登録済みを確認した。公開設定は利用者が操作する方針で、公開前に機密情報と個人情報を点検する。

### 実装した変更

1. v0.3のSwift推定エンジンとSQLiteローダーを再利用し、`ios/RailVelo.xcodeproj` と共有scheme `RailVelo` を作成した。iOS 16以上、iPhone縦画面、日本語、SwiftUI、Swift Charts、OS標準SQLiteを採用した。
2. 実GPSとリプレイを共通の`ObservationSource`へ接続した。リプレイは同梱合成GPSを25倍速で処理し、セッションの`live`/`replay`を保存して実記録と区別する。
3. `RideProcessor`を追加した。速度・精度・位置・時刻の検査、古い/未来/逆行観測、異常加速度、位置変化との不一致、座標跳躍を扱い、有効な実測速度だけを表示・最高速度へ採用する。新観測が5秒以上来ない場合はアプリの監視で欠測を入力する。
4. 推定とDB処理を直列キューへ集め、画面状態をMainActorで更新する。Networkは初期化時に読み込み、位置更新ごとに線路DBを再読込しない。
5. `RideStore`を追加し、別の履歴SQLiteへセッション・元観測・推定結果・駅イベント・除外理由・状態遷移をトランザクションで保存する。開始・一時停止・再開・終了、中断復旧、確認付き削除、CSV出力を接続した。
6. 現在/最高速度、GPS精度と状態、路線・方面、前後駅、残距離・進捗・候補支持度、60秒/5分/全体グラフ、履歴画面を作成した。直近バッファと全体グラフ点数を制限し、欠測・無効速度・一時停止を線で結ばない構成とした。
7. 実GPSの記録中だけ背景位置情報を有効化し、一時停止・終了・リプレイでは停止する。OS終了後の自動復帰による無欠測記録を保証せず、残る未終了セッションを再起動時に中断扱いへ変更する。
8. 履歴保存ディレクトリに端末ファイル保護とバックアップ除外を設定した。CSV共有先は本人が選び、一時出力は次のエクスポート時に24時間超の古いものを削除する。位置履歴を外部へ自動送信する機能は追加していない。
9. Core/SQLiteのXCTest 12件に加え、RecordingのXCTest 17件を作成し、macOS CIで29/29件の成功を確認した。PythonもWindowsとengine CIで36/36件成功。保存時刻とGPS/リプレイ時刻を分離し、中断復旧の終了時刻が開始時刻より前にならない処理と既存DBへの列追加も試験した。
10. Swift/Python試験と17 fixture比較はengine CIで実行し成功した。アプリCIへXcode選択、Simulator/端末向け署名なしビルド、built Info.plist/同梱リソース、リプレイ起動、DBの有効速度/確定推定確認、ライト/ダーク画像、中断復旧を定義し、こちらも成功した。アプリCIではengine試験を重複実行しない。
11. `TECHNICAL_DESIGN_v0.4.md`、`APPLE_SETUP.md`、`DEVICE_TEST_PLAN.md`を作成し、READMEと検証記録を更新した。v0.1/v0.2設計書本文の未取得は継続する。

### 実行・Apple設定の状態

- [アプリCI](https://github.com/KANABUNN/RailVelo/actions/runs/39453148802) がcommit `8808fdd9f4bccf9122b7dceedfac99b60285a0eb`でsuccess。`macos-26` arm64、Xcode 26.6（17F113）/ iOS 26.5 SDK、iPhone 16 Simulator runtime 26.5で、Simulator/端末向け署名なしビルド、built Info.plist/同梱リソース、リプレイDB5観測・有効速度5件・matched3件、`interrupted`への中断復旧が成功した。
- ライト/ダークは実画像の背景3点平均輝度（約0.9648 / 0.0）と目視で切替を確認した。画像では合成速度71.7 km/h、鹿児島本線・博多方面・駅間進捗を確認。グラフは画像の下にあり、今回の目視に含まれない。UI全操作・VoiceOverも未検証として残す。
- [engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39447558500) がcommit `e206e23aacaaf9dcc298c54557808fda13ce40ba`で成功。Xcode 16.4 / iOS Simulator 18.5 SDK、Python36件、Swift29件、Core Location/SQLiteのiOS Simulator向けライブラリビルド、17 fixture全件のPython/Swift比較に成功した。
- engine runnerは`macos-15-intel`、アプリrunnerは`macos-26`（arm64）。関連pathのみの自動実行とブランチ単位のconcurrencyで実行数を抑える。
- 過去試行ではprivate実行のアカウント制約、Network/type guardとpkg-config経由ホストdylib参照、Simulatorの待機・scene設定・ダーク画像反映を修正した。現在表示は観測時刻から5秒で失効させ、古いキュー結果の再表示と受信継続中の偽欠測を防いだ。[前段CI](https://github.com/KANABUNN/RailVelo/actions/runs/39450278021) はDB・中断復旧まで成功したがdark画像がlightだったため、最終runで画像の輝度検査と目視を追加して成功を確認した。
- 利用者の明示許可を得て、合成リプレイの失敗画面と件数を診断artifactへ保存する設定を追加した。保持期間は1日で、実GPS・個人データは対象に含めない。
- Appleのアカウント画面を読み取り、有効な会員資格と契約同意済みの状態を確認した。Explicit App ID `jp.kb-dev.railvelo`（Description: RailVelo）の登録完了を一覧で直接確認した。App Store Connectアプリ「RailVelo」（ID `6824978233`、日本語、SKU `railvelo-ios`、Bundle ID `jp.kb-dev.railvelo`）も登録完了を確認した。
- 内部グループ「本人検証」を作成した。自動配信オフ、テスター0人、ビルド0件、公開リンクなし。招待・証明書/APIキー生成・署名・アップロードは行っていない。個人情報を除いたApple画面証跡はリポジトリ外に保存し、公開ソースへ含めない。対象buildの割当、TestFlight配布、iPhone導入は未完了である。
- 署名・TestFlight・iPhone実GPS・背景継続・長時間/電池・実走は未検証。Simulatorでの限定したリプレイ、DB、中断復旧、ライト/ダークの成功と、iPhone実機受入を区別する。

### 公開前の点検と履歴整理

初期の1 commit・157 blob、SQLite 2個、原典ZIP/PDF/HTMLを読み取り点検した。既知の秘密鍵・トークン・具体的credentialのパターンは0件。旧DBの個人記録用4テーブルは全て空、fixtureは固定seedの合成GPS。原典5ファイルは取得manifestのSHA-256と一致した。公式ライセンスHTMLの公開連絡先は原典由来として区別した。

初期commitのauthor情報とログのユーザー名入りローカルパスを整理した。旧commitのGitHub上での直接参照が残るため、既存リポジトリをprivateの退避先へ移し、新しい`RailVelo`を作成した。clean root commit `2e238881f4a3428eec79a51e03f8ce178db75408`を反映し、旧commitを新リポジトリからfetchできないことを確認した。利用者が公開設定を変更したことをGitHubのリポジトリ情報で確認し、アプリソースも反映した。署名資料・実走CSV・端末ログは今後もGitへ追加しない。

最終反映前の整合性確認用に`update_manifest.py`を追加した。変更をステージした後、`python scripts/update_manifest.py`でGitの正規内容からSHA-256一覧を再生成し、`python scripts/update_manifest.py --verify`で一致を確認した。作業ツリーの改行変換後の内容ではなく、ステージ済み内容が対象である。最終差分と到達可能な全履歴の公開監査でも秘密情報・個人メール入りcommit情報の検出はなかった。最終反映は文書・監査/整合性補助のみで、検証済みアプリ・エンジンのソースは変更していない。

### 再開する順序

1. 最終反映時にステージ内容とSHA-256一覧を照合し、未検証のグラフ目視・UI全操作・VoiceOverの確認を進める。Swift29件・Python36件・17シナリオ比較・アプリビルド・Simulatorリプレイ/DB/中断復旧/ライト・ダークは成功済み。
2. 署名資料とアップロード方法を整え、本人用の内部TestFlight配布を進める。認証と秘密鍵の設定は利用者が安全な画面で行う。
3. 署名付きアップロード、Apple処理完了、本人用テストグループと対象buildの割当を確認する。
4. iPhone 16へ導入し、`DEVICE_TEST_PLAN.md`に従って前面GPS、拒否・概算位置、古い速度・欠測、ロック/別アプリ、中断復旧、保存・CSV、電池を確認する。
5. 門司港〜博多の実走ログで並走・折尾・トンネル・駅イベントを評価し、未較正の閾値と長時間性能を改善する。

## v0.5 追加作業（2026-10-21）

実機導入を優先し、時刻表API・遅延推定・一般公開・外部テスターを追加しない方針で進めた。

- 実リプレイを操作するXCUITestを追加。グラフ3期間・実画素、スクロール、開始/一時停止/再開/終了、履歴/削除、CSV共有画面、大きい文字と明暗Accessibility Auditを対象にする。実際のVoiceOver読み上げは別の実機項目とした。
- 既存履歴へ受信時刻/保存処理開始時刻と診断テーブルを追加し、GPSエラー・権限・アプリ状態を保存する。先頭36列を維持した39列CSVへ診断/セッション要約を追加。旧DB移行、CSV consumer、対象限定削除のSwift試験を追加した。
- `analyze_ride.py`、本人の正解/駅時刻メモ・端末測定の雛形と非公開運用手順を作成。不明を正解に含めず、線路との残差を独立した実測精度と呼ばず、CPU/メモリ/電池が未測定なら数値を作らない。
- source `083e16c`の[engine CI](https://github.com/KANABUNN/RailVelo/actions/runs/39524933942)でPython52件、Swift32件、実Swift出力CSV→Python解析、17 fixture比較とiOSライブラリが成功した。アプリ2種ビルドと既存smokeも成功したが、画像取得中のfixture自然終了で中断復旧の試験前提が失われた。復旧直前に新規実リプレイを開始し、対象セッションIDを固定する試験へ修正した。新規UI試験は後続CIの結果待ち。
- 手動起動・main祖先の完全SHA・同一SHAのengine/app成功を要求するTestFlight内部限定配布処理を作成。秘密を非公開一時領域へ閉じ込め、署名資料・署名後アプリを照合し、直接アップロード後に`VALID`/`INTERNAL_ONLY`を読み取り確認する。公開成果物は許可項目のみの状態JSONを1日保持する。
- 配布の独立レビューで復元snapshotの更新中断に対応。固定分類/終了コード以外の失敗内容を公開しない。Apple実発行profileのiOS/xrOS/visionOS互換区分に対応し、YAML plain scalar中のcolonを複数行形式へ修正した。ローカルPython74件が成功、GitHubに配布workflowが有効として登録された。
- 利用者が新しい署名資料/APIキー発行・GitHub Secrets保管・本人限定upload/割当を許可。新Distribution証明書（2027-10-21まで）と生成鍵の一致、専用App Store profileの対象/期限/証明書一致、API鍵の形式をローカルで確認した。既存アプリの秘密情報は流用していない。
- Environment `railvelo-testflight`をmainブランチのみ・tag 0件・本人reviewer必須・admin bypass無効とし、7 Secretsを登録して名前を確認した。値はソース・公開ログ・画面証跡に記載していない。鍵は暗号化しowner/SYSTEM ACLで保管。登録中だけのCodex読取権限は追加の明示許可後に付与し、登録後に削除を確認した。
- 本人端末はiPhone 16 / iOS 27.0.1、TestFlight導入済みという回答を得た。RailVeloの署名・Apple認証・アップロード・本人割当・端末導入・実GPS・背景・電池・実走の成功とは区別する。
- source `3619ecc`のengine CIはPython74件・Swift32件・相互運用・17 fixture・iOSライブラリが成功。アプリCIは両ビルド・smoke・中断復旧が成功し、新UI試験でグラフ3期間の画素を確認したが、速度表示のDynamic Typeと履歴の画面遷移で失敗した。ScaledMetric、早期pause、同一履歴IDの保護確認へ修正し、Dark試験の独立実行とPNG添付の書き出しを追加した。実アプリの暗号機能はOSに依存し、独自/第三者暗号を含まないため免除宣言を設定した。

最新のCI・配布・実機結果は`VALIDATION.md`へ追記する。実走ログは未取得で、実走精度の評価値は確定していない。
