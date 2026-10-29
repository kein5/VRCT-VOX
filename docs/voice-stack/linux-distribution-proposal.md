# Linuxパッケージ配布案（2026-10-29）

第一候補は **`vrct-tts-bin`（x86_64、Arch/CachyOS向けAUR）**。
検証したバージョンのバイナリ配布物を固定SHA-256で取得する方式を推奨する。
これは配布方式の案であり、完成したPKGBUILDや登録・公開の報告ではない。
存在しないrelease URLや仮のchecksumで「インストール可能」とは扱わない。

## 比較

| 方式 | 利点 | 今回の制約と判断 |
|---|---|---|
| AUR `vrct-tts-bin` | 利用者側で大型Python/Rustビルド不要。pacmanで更新・削除を管理 | 固定バイナリと依存一覧、再配布条件、クリーン環境での受入れが先。第一候補 |
| AUR `vrct-tts` / `-git` | ソースからビルド可能。依存をArch側へ寄せやすい | rolling Pythonと既存pin、speech.cppの固定ハッシュ信頼境界、再現性ある推論依存の整理が必要。後続候補 |
| AppImage | 他のLinuxにも単一ファイルを渡せる | パッケージマネージャではない。アプリ全体のglibc/WebKit互換性と音声経路の実機検証が必要 |
| Flatpak/Flathub | 依存の分離、更新経路を提供 | PipeWire graph制御、pidfd、外部VC worker/venv/モデルパス、GPU権限をPoCで確認する必要。PulseAudio権限だけで十分とは判断しない |

[Tauri公式AUR手順](https://v2.tauri.app/distribute/aur/)はソース版とバイナリ版の例を示している。
その依存リストをVRCT-TTSへそのまま転記せず、実際のリンクとPython native依存から確定する。
[AppImageの公式手順](https://v2.tauri.app/distribute/appimage/)は古い対象環境でのビルドを求める。
speech.cpp単体のGLIBC_2.34確認から、アプリ全体の下限を推定しない。
[Flatpak権限仕様](https://docs.flatpak.org/en/latest/sandbox-permissions.html)との照合は未完了。

## パッケージ境界

- 製品名`VRCT-TTS`、実行名`vrct-tts`、identifier `io.github.kein5.vrct-tts`。
  本家`vrct`を`provides/replaces/conflicts`へ入れて置換しない。
  source/bin相互の排他だけを将来のPKGBUILDで定義する。
- 不変の本体・Python runtime・native helper・固定speech.cpp・通知を専用配置へ置く。
  候補は`/usr/lib/vrct-tts`。開発sidecarと分けた[Linux凍結ビルド](linux-build-pipeline.md)を使用する。
- 設定、ログ、cache、ユーザーモデルは専用の可変領域へ分離する。
  [XDG仕様](https://specifications.freedesktop.org/basedir/latest/)に沿う移行が必要。
  凍結Linux版はXDGのconfig/data/cacheと`VRCT_*_DIR`を使用する。開発/Windowsの既存パスは保持する。
- OCR、speech.cpp/RVC/Seed-VC重みと参照音声を入れない。既存faster-whisper依存のSilero VAD資源は別途一覧化して監査する。特にMia2026は検証専用。
  speech.cpp本体とモデルの配布許可を混同しない。
- RVC/Seed-VCの大規模依存環境は初版では外部指定を継続する案。
  Seed連携のGPL、RVC環境のpraat-parselmouth GPL、soxrのLGPL、PyAV/FFmpeg等を別途監査する。
- package install scriptからユーザーのHOMEを書き換えたり、音声サービス全体を再起動したりしない。
  PipeWireテンプレートは同梱resourceとし、アプリの明示操作で専用graphを作る。
- 組込み更新は無効のまま。AUR/pacmanで導入した本体をアプリ自身で置き換えない。
- owned audio/helperで必要な`PIDFD_THREAD`はLinux 6.9以降の機能。
  `linux`パッケージを強制してユーザーのkernelを置換せず、起動時の機能検査で案内する。
  [pidfd_open仕様](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)。

## 公開までの順番

1. checkout不要のLinux runtimeを作り、上記の不変/可変パスを分離。
2. source ZIP/binary tar.gz、全同梱ライセンス、対応ソース・再リンク手順、SBOMを整備。
3. クリーン環境で起動、音声経路、停止、更新、削除後の設定保持、本家との共存を検証。
4. Trail of Bits Skillsで依頼済みの監査を実施し、重要な未修正事項を解消。
5. 実URL/hashを用いたPKGBUILDと`.SRCINFO`を作成し、clean chroot、namcap、インストール試験。
6. ユーザーがレビューできる候補を示してから、配布公開/AUR登録の実施範囲を確定。

[PKGBUILD仕様](https://man.archlinux.org/man/PKGBUILD.5.en)、
[クリーンchroot手順](https://wiki.archlinux.org/title/Building_in_a_clean_chroot)、
[.SRCINFO](https://wiki.archlinux.org/title/.SRCINFO)を基準とする。
AUR公開ルールの一部は取得時にAnubisで遮断されたため、投稿前に現行原文を再確認する。

2026-10-29の公開AUR RPCで`vrct`は存在し、問い合わせた`vrct-tts`、`vrct-tts-bin`、
完全一致の`speech.cpp`は返らなかった。これは名前の予約ではなく、別名package不存在の証明でもない。
元データと公式資料は`tmp/voice-resume/research/linux-distribution/`に保存。
現在の実装・検査状況は[配布境界報告](fork-distribution-isolation.md)を参照。
