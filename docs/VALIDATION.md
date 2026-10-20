# 実行確認と受入範囲 — v0.4

前工程確認日：2026-10-20、v0.4更新日：2026-10-21。作業環境：Windows、Python 3.14.6、SQLite 3.50.4。v0.4の追加実装と実行待ち項目は以下の表で区別する。

| 項目 | 結果・証跡 |
| --- | --- |
| 前工程SQLiteの原本保全 | 52ファイルのSHA-256一致。指定元を変更せずコピー |
| 前工程のデータ検証 | 30/30。`upstream-validation.json` |
| 前工程の接続試験 | 5/5。`upstream-topology-tests.txt` |
| 今回のSQLite/JSON生成 | 22/22。`data-quality.json` |
| DB再生成 | 繰り返し生成で同一SHA-256。`data-quality.md` |
| Python自動テスト | **36/36成功**。v0.4作業でも再実行して成功。前工程の記録は `test-results.txt` |
| GPS合成走行評価 | **17シナリオ・1,213観測**。`evaluation.json`、`evaluation.md` |
| 同梱SQLiteによる全区間リプレイ | JSON版と同一結果。自動テストと`release-checks.json` |
| Swift Core/SQLite XCTest | **12件をソース作成、コンパイル・実行未確認** |
| Swift Recording XCTest | **13件をソース作成、コンパイル・実行未確認**。速度異常・古い/未来/逆行観測、pause、SQLite再読込・復旧・ロールバック、間引き、CSV・削除を対象 |
| Python/Swift共通データ比較 | 比較プログラムと全件CI手順を作成。**両実装の実行比較は未実施** |
| SwiftUIアプリとXcode設定 | Xcodeプロジェクト、画面、Core Location接続、直列推定/保存、履歴、CSV、リプレイ、背景設定、プライバシー設定を作成。**実コンパイル未確認** |
| iOS Simulator / 端末向け署名なしビルド | workflowを作成。**ビルド未検証** |
| Simulatorリプレイ・DB・画面・中断復旧 | 自動確認の定義を作成。**起動・画面検査未実施** |
| 最初のGitHub Actions実行 | privateリポジトリの支払い・利用上限に関する理由で約6秒後、処理開始前に失敗。**コンパイル結果なし**。下記参照 |
| iPhone 16への導入・前面GPS・背景GPS | **未実施** |
| 実走GPS | **ログなし、未評価** |
| 長時間・電池・端末ファイル保護・共有先 | **実機未検証** |

## v0.4のCI・Apple・公開準備

最初の [GitHub Actions実行](https://github.com/KANABUNN/RailVelo-private-backup-20261021/actions/runs/39443935454) はアカウントの支払い・利用上限に関する理由でジョブ処理開始前に失敗した。コードのビルド失敗を示すログは得られていない。公開準備後にmacOS実行を再試行する。成功したrun URL、対象commit、Xcode/SDK、試験件数、ビルド・画面・DB検査の結果を追記するまでSwift/iOSは未検証とする。

Apple Developer Program登録済みという利用者の回答に加え、有効な会員資格と契約同意済みの状態を画面で読み取り確認した。本アプリのApp IDとApp Store Connectアプリは登録準備中。署名資料設定、署名付き配布、Apple処理完了、本人用TestFlightグループ割当、端末導入は未完了である。本人のアカウント情報・Team ID・秘密鍵は記録しない。[導入手順](APPLE_SETUP.md)

公開前監査では初期の全1 commit・157 blobとSQLite 2個を確認した。既知の秘密鍵・トークン・APIキー等のパターンに該当する機密は検出されなかった。旧SQLiteの`rides`、`gps_samples`、`match_results`、`station_events`は全て0行で、同梱fixtureは固定seedの合成GPS。原典5ファイルのSHA-256は取得記録と一致した。公式CC HTMLには原典の公開連絡先が含まれる。

初期Git履歴のauthor情報とログのユーザー名入りローカルパスを整理した。GitHub上で旧commitを直接参照できる問題を避けるため、既存リポジトリをprivateの退避先へ移し、新しい`RailVelo`へ整理済み履歴を反映する準備を進めている。新リポジトリの再監査後、公開設定は利用者が行う。検出なしはパターン検査と内容確認を行った範囲の結果であり、将来追加する実走CSVや署名資料まで安全と認定するものではない。

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

SwiftはmacOS/Xcodeで `swift test --package-path swift` と `.github/workflows/swift.yml` のSimulator・全共通データ比較を実行する。アプリは `.github/workflows/ios.yml` または [Apple手順](APPLE_SETUP.md) の署名なしビルド手順で確認する。GitHubへの初回反映は実施済みだが、最初のmacOS CIは上記のアカウント要因で実行開始できなかった。CIまたはMacでの実行が成功するまでSwift/Pythonの同等性とiOSビルドは未確認である。

## 次工程の条件

v0.3の `SWIFTUI_HANDOFF.md` を継承し、アプリの実装設計は [v0.4技術設計](TECHNICAL_DESIGN_v0.4.md) に記録した。まずSwift試験、17シナリオ一致、Simulator/端末向けビルドとリプレイ起動を実行する。続いて署名とTestFlight導入を行い、[実機試験計画](DEVICE_TEST_PLAN.md) に従って権限・前面GPS・欠測・背景・OS終了・保存・CSV・電池・実走を評価する。

現地ではイベント閾値、信号待ちと停車の識別、折尾の駅線形、並走・分岐、トンネル復帰、端末性能を確認する。v0.1/v0.2設計書本文は未取得の制約を維持する。アプリソースを作成した段階と、iPhoneでの受入完了を分けて扱う。
