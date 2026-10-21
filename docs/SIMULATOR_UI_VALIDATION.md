# Simulator UI検証 — v0.5

更新日: 2026-10-21。

対象：macos-26 arm64 / Xcode 26.6 / iOS 26.5 SDK・runtime / iPhone 16 Simulator、同梱の合成GPSリプレイ。実GPSや個人アカウントは使用しない。XCUITestは実アプリのReplayObservationSourceから、実GPSと共通の推定・SQLite・CSV経路を使用する。

下表は最終配布候補`afd55bb`のCIと実画像で確認した結果である。

| 検証項目 | 方法 | 結果 |
| --- | --- | --- |
| 速度グラフの実描画 | 画面をスクロールし、グラフ領域の実画像内にデータ色の画素を確認 | 点の画素検査・3期間の目視が成功。時刻目盛の重なり解消も確認 |
| 60秒・5分・全体 | 3ボタンを操作し、選択状態・観測件数・実描画を検査 | 3期間の切替・点描画は成功 |
| 記録開始・一時停止・再開・終了 | 実リプレイを操作し、非同期保存の完了を待つ | 一連の操作と永続化待機が成功 |
| 履歴表示・保護・削除 | 一時停止中は削除不可、終了した今回作成の合成履歴だけ削除 | 表示・保護・対象限定削除の操作が成功 |
| CSV | SQLiteから生成されたCSVのiOS共有画面を表示、送信せず閉じる | ネイティブ共有画面の表示とキャンセルが成功。実機のFiles保存は別試験 |
| 明暗表示・大きい文字 | 実際のSimulator設定とAccessibility Audit | Light/Dark・拡大文字の指定監査とスクロールが成功 |
| VoiceOver | 基本ラベルと説明は自動検査。音声・フォーカス移動は本人のiPhoneで確認 | 実際の読み上げは未実施 |

自動監査はメイン画面の指定時点で実行し、LargeTextはhitRegion・sufficientElementDescription・textClipped・dynamicType、Darkは前3項目を対象とする。スクロール後のグラフは操作・画像でも確認する。実際のVoiceOverによる音声・フォーカス移動や、全画面・全状態の網羅的な監査を済ませたとは扱わない。

XCUITestの各操作画像は`ui-light.xcresult` / `ui-dark.xcresult`に保存し、直接参照できるPNGとmanifestを`ui-light-screenshots` / `ui-dark-screenshots`へ書き出す。公開できるのは、この使い捨てSimulator上の合成データによる検証成果物だけ。ユーザーが実機で記録したファイルはCIへ送らない。

## 実行と目視の証跡

**最終候補成功:** `afd55bb73ac919feed936a943899da115a6cd2b5`の[run 39531634651](https://github.com/KANABUNN/RailVelo/actions/runs/39531634651)。両ビルド、明暗smoke、中断復旧、3件のUI試験が成功した。LargeText 35.146秒、全操作101.920秒、Dark 20.683秒。通常の60秒/5分/全体は24時間表記3目盛、拡大文字は2目盛で、欠け・重なりがなく、説明文や操作ボタンを妨げないことを実画像で確認した。Darkの軸も目視した。

最終候補のartifactは`12315588317`、ZIP 13,122,167 bytes、SHA-256 `e8f58321c9afca68bc110f3ef94926597a9c724f5436eda1b0c8a4d4baf760e0`。取得してハッシュ照合後、`ui-light-screenshots` / `ui-dark-screenshots`のmanifestとPNGを確認した。60秒`4536AED9-B9E6-445E-A2EA-5848914C810B.png`、5分`7FA8455B-8AD8-4C8A-8B3D-936606C12F8C.png`、全体`4AB90E29-A0D0-442A-8E2A-689B966B06BC.png`、拡大文字`FB148119-2532-4BB7-98F2-5955EAA1DD3A.png`を含む。

先行する`52464c9f58d1b2435a425a32dad7c6251699e066`の[run 39529981900](https://github.com/KANABUNN/RailVelo/actions/runs/39529981900)でも全stepが成功した。終了確認の重複要素への対応と、進捗の44pt以上の読み上げ要素を実際に再試験した結果である。artifact `12315636116`をハッシュ照合して取得し、共有シートにRailVelo-replayのファイルが載ること、削除確認と対象行の削除、履歴詳細の日時/最高速度、Darkの進捗表示も目視した。X軸の視認性は上記最終候補で修正した。

`512ea0335481719a13830c2fc87477a421c58a25`の[run 39528724495](https://github.com/KANABUNN/RailVelo/actions/runs/39528724495)で、両アプリビルド・smoke・中断復旧、文字拡大監査が成功した。全操作試験は再開後の終了確認で、iOSの親子Button重複を単一要素として検索したため失敗した。Dark監査は駅間進捗の細いProgressIndicatorの領域不足で失敗した。確認ボタンを明示IDで操作し、進捗は割合・次駅距離を含む44pt以上の単一読み上げ要素へ修正した。監査項目の除外で成功扱いにはしていない。

同runの`ios-build-evidence`（artifact `12315121426`、SHA-256 `1c20f1d5e427e92eb1daad200dc73a16b4e37b60d118e1bae12fa918509ff653`）を取得・ハッシュ照合し、60秒・5分・全体と大きい文字の実画像を目視した。PNGは`ui-light-screenshots/manifest.json`等で添付名と照合できる。点描画と切替は確認したが、時刻ラベルの重なりが残ったため、最終候補で表記と目盛数を修正した。成果物は公開先で1日保持、手元ではGit除外対象の`artifacts/`に保存する。

## 合格へ拡張しない範囲

同梱fixtureの観測間隔は25秒で、連続観測として結ぶ閾値を超えるため、今回のグラフは点として描画される。点の実画素を確認した結果を、短い取得間隔での連続線・実GPS・列車での実走の合格へ拡張しない。連続線と実際のVoiceOver読み上げはiPhoneの初期試験で確認する。合成GPSを使ったCLI/SQLite試験とは別に、端末の位置許可・ロック中の記録・共有先・電池を実機で確認する。

利用者の申告端末はiPhone 16 / iOS 27.0.1、TestFlightアプリはインストール済み（2026-10-21）。RailVeloの端末への導入・起動、実GPSの連続線、実際のVoiceOver、背景・ロック中の記録、OS終了復旧、FilesへのCSV保存、長時間・電池・実走は全て未検証。SimulatorのiOS 26.5での結果と分け、[実機試験計画](DEVICE_TEST_PLAN.md)に従って受け入れる。
