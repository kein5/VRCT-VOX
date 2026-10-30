# Steam Frame接続中のVRCT-TTS実機試験

この試験は、本番AppImageのGUIから実音声モデルを呼び、生成音声をmanaged仮想マイクへ出し、実VRChatの入力接続を確認する。VRChat内の録音・再生、他プレイヤーへの到達、HMD内のQuickChat入力は別の検証項目である。

## 再実行する条件

- Linuxの描画中のデスクトップ、tauri-driver、WebKitGTK WebDriver、xdotoolが利用できること。
- Steam FrameとSteamVRが接続済みで、VRChatが自分だけの招待制インスタンスにいること。
- `vrct.managed.source`などのmanaged経路を準備し、sourceがミュート済みであること。VRChatだけをこのsourceへ接続し、出力先を`vrlink-sink`にする。
- 実マイクの混入を防ぎ、変更前のデバイス、ミュート、音量、既定デバイス、所有プロセスを別途記録すること。
- ローカルIrodoriサーバーが起動済みであること。モデルの取得や音声サービスの再起動は試験ツールでは行わない。

```sh
.venv_linux/bin/python tools/native_frame_acceptance.py \
  --app /absolute/path/to/VRCT-TTS.AppImage \
  --output /absolute/path/to/new-results-directory \
  --server http://127.0.0.1:PORT \
  --vrchat-pid PID \
  --vrchat-window X11_WINDOW_ID \
  --seconds 600 --skip-ime
```

出力ディレクトリは新規に作る。通常のVRCT設定とは別の設定で試験アプリを起動し、OSC送信、マイク文字起こし、自動モデル取得を無効にする。試験用QuickChatキーはCtrl+Alt+Shift+F9である。通常設定のShift+Tとは別条件として扱う。

`--skip-ime`は実IMEを検証しないという明示的な指定である。実Fcitx/Mozcを試す場合は外し、必要に応じて専用ydotooldのソケットを`--ime-socket`で渡す。確定済み日本語のWebDriver入力だけをIME変換の成功とは扱わない。ホスト側の経路準備・復元と専用ydotooldの終了は呼び出し側が管理する。

Fcitxのactive状態だけではMozcの日本語変換を保証しない。IME試験では、日本語が確定したこと、確定Enterのキー解放より後に観測した受付件数が不変であること、次のEnterで1回完了することを確認する。GTKではDOM compositionイベントが出ずキーコード229が届く場合があるため、イベント名だけで変換失敗と判断しない。

## 合否の根拠

- 固定seedの参照音声を2回生成し、PCMのバイト一致を確認する。各通常送信では、実バックエンドの受付・完了件数の差分と、仮想マイク録音に参照音声が1回現れることを照合する。
- 停止、保持ミュート、OFF中の新規送信、ON直後の古い音声の再生を個別に検査する。無音判定は新しいPCMが十分な時間連続して到着した場合だけ有効とする。
- 録音プロセスの終了、readerの例外、時間の欠落を無音成功にしない。各録音区間と全体の録音を検査する。
- `voice_route_watch.py`は`pw-dump --monitor`が報告した変化を記録し、VRChatのPID、入力sourceのcookie/serial、入力stream、activeな入力linkを照合する。途中の誤接続は、その後元へ戻っても失敗として残す。
- 出力側は接続先の隔離を検査する。ゲーム音の生成・休止に伴うlinkの交渉やidleなstreamの終了は、再生先が正しい限りマイク障害と区別する。出力の連続稼働やHMDへの可聴音をこの判定で証明しない。
- `pw-dump`は変化を集約することがあり、同じ接続上のheartbeatや終端syncはない。結果は`received_pipewire_changes`の範囲であり、あらゆる瞬間的なfallbackが存在しなかったという保証ではない。
- QuickChatを閉じた後、追加のwindowactivateを挟まず、OSのactive windowが実VRChatへ戻ることを確認する。これはHMD内操作やゲーム内の全キー入力を保証しない。

各ケースは途中では暫定観測として記録する。全体録音、監視のdrainと終了、試験アプリ終了、sourceミュート、各cleanupの完了後に合格を確定する。cleanupは独立して全て試み、失敗を集約する。cleanupだけの失敗でも終了コードを失敗にし、元の試験例外がある場合は保持する。

録音・経路監視の区間は試験アプリの終了前までであり、その後の終了・ホスト復元は状態確認として別に記録する。

## 2026-10-30の確認結果

Quick Chat前面修正版AppImage（SHA256 `11c9d3e8cd34836223e9b48fb42c78754fee59aa5f8b26aa55d9f404e71a0e17`）で604.9859秒・28ケースが合格した。main GUIからの固定文20回（うち定期18回）、停止/保持ミュート、無音3件、QuickChatのEsc復帰3件を含む。100msを超えるPCM readerのread間隔は0件で、ネットワークや全ての音切れを計測した意味ではない。

関連回帰試験53件成功。既存レビュー担当も保存PCMと全16,872バッチを独立再計算し、明記された測定範囲のPASSを確認した。live validatorと最終validatorでの保存イベント再検査は別に記録している。

別の短時間試験では実Fcitx/Mozcのローマ字から日本語への変換、確定Enterでは未送信、次EnterでQuickChatからTTSを1回完了することも合格した。保存仮想マイクPCMとの照合も1回、相関0.99587。条件はGTK Fcitxモジュール、keyboard-us + mozcの一時グループ、Hiragana初期モード、uinputキーボードであり、元設定・物理キーボード・通常Shift+T・変換中Escは未検証。

**VRChat内部再生、他プレイヤーへの到達、HMD内入力は未検証。** 試験用ノードと仮想キーボードを撤去し、音声設定・IME設定は復元済み。SteamVR、通常VRCT、音声サービスは維持した。

ローカルの詳細記録は `tmp/steam-frame-vrchat-loop-2026-10-30/report.md`。10分試験は`stability-12/report.json`、追加IME試験は`quick-ime-fresh-19/report.json`、その最終復元は`quick-ime-fresh-19-restore.json`。`tmp`は配布物に含めない。

## 参照資料

PipeWireの[変更通知を出力するpw-dump](https://docs.pipewire.org/page_man_pw-dump_1.html)と[loopbackの仮想source/sink](https://docs.pipewire.org/page_module_loopback.html)、[Fcitxの入力環境変数](https://fcitx-im.org/wiki/Input_method_related_environment_variables/en)、[KDEのCJK入力とXWayland互換性](https://linux.kde.org/docs/cjkv-input/)を参照した。今回の調査原文と試験記録は`tmp/steam-frame-vrchat-loop-2026-10-30/`に保存している。
