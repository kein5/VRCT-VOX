# 実VCへ進むための導入候補と同意待ちの範囲

2026-10-28。モデル不要の入力転送UIは[実Tauri受入れ](source-controls-report.md)まで完了した。
次はSeed-VC Realtimeを**製品への採用を確定せず、別プロセスの実機PoC候補**として検証する案。
2026-10-28にユーザーが取得とPoCを明示承認。固定12ファイル（1,523,519,558bytes）の取得とhash照合を完了した。
[取得記録](seed-vc-acquisition.json)。runtimeの実行互換・変換試験はこれから行う。

## 比較と選択理由

| 候補 | 確認した点 | PoCに残る条件 |
|---|---|---|
| Seed-VC Realtime | 固定codeを読める。入力monitorとVCの分岐、VAD無音、推論例外→無音が実装にある。5モデルの固定候補を列挙可能 | GPL-3.0 code/model。1〜30秒の許可ある参照音声。状態通知adapter、実ロード・品質・遅延・GPU競合を検証 |
| VCClient現行2.x | 固定配布一覧でWindows binaryとLinux aarch64 binaryを確認 | このrevisionにLinux x86_64 ZIPは見つからない。旧公開server APIと現行binaryの同一性は未確認。Beatrice rc0配布物の非商用・再配布許諾条件もある |
| RVC + AISO-HOWATTO | モデル配布説明はMITで商用・再配布可と記載。55,074,309 bytesの候補 | 作者は約2秒chunkを推奨し、対応版も古い。現行engineとの互換と低遅延品質は未確認 |

プロセスが生きていることや音声sourceが存在することだけでは、変換ON・bypass・推論失敗を区別できない。
Seedの既存performance callbackも変換成功の証明ではない。独立engine側で状態通知を追加するPoCが必要。
その実装・故障試験が通るまではconvertedモードとしてUIに公開しない。

## 取得する場合の具体的なモデル候補

[固定revision・ファイル・期待hash・サイズの一覧](seed-vc-poc-artifacts.json)。
合計**1,523,519,558 bytes（約1.524GB）**。Python/CUDA等のruntime依存は別で、uv隔離環境で解決する。
表のhashは配布元メタデータの期待値であり、取得済み重みの照合結果ではない。

| 配布元／ファイル | 用途 | モデルカードの表記 |
|---|---|---|
| Plachta/Seed-VC `DiT_uvit_tat_xlsr_ema.pth`＋tiny設定 | 変換本体 | GPL-3.0 |
| funasr/campplus `campplus_cn_common.bin` | 話者特徴 | Apache-2.0 |
| FunAudioLLM/CosyVoice-300M `hift.pt`のみ | 波形生成 | Apache-2.0 |
| facebook/wav2vec2-xls-r-300m `pytorch_model.bin`＋設定 | 内容特徴 | Apache-2.0 |
| funasr/fsmn-vad `model.pt`＋設定・cmvn・カード | VADの明示的な代替候補 | Apache-2.0 |

**VADは既定artifactと同じだとは扱わない。** 元engineはModelScopeの`fsmn-vad` revision`v2.0.4`を取得する。
その全artifactを確認できていないため、既定の自動取得は使用しない。
HFの上記固定VADをローカルパスで明示する代替案を検証する。
FunASR1.2.7の公式配布sourceでローカルパス指定はdownloadを迂回し、設定の
`FsmnVADStreaming`をロードする経路があることを確認した。実checkpoint互換は未検証。
`trust_remote_code=False`、既存ファイル限定とネットワーク抑制を条件にし、不足時は閉じる。
model repositoryのサンプル音声・画像・不要な追加checkpointは取得しない。

GPL対象の外部エンジン/adapterと既存MITアプリの配布物・ライセンス表記を分けて管理する。
プロセスを分けただけでライセンス条件が消えるとは判断しない。実配布前の対応ソース・通知の確認を別ゲートにする。
参照音声は本人またはこの用途の許可があるものを必要とし、公開サンプルや著名人の音声を勝手に使わない。

## 同意後のPoCと合否

1. 固定候補だけを作業用領域へ取得してhash照合。runtimeはuvで隔離し、無断の追加モデル取得を止める。
2. engine準備・stream開始・変換ON・bypass・推論失敗・停止を別状態にし、健康な変換を確認できない間は転送を閉じる。
3. 私有音声経路で許可ある参照音声と同意済み試験入力を使用。モデル単体・block処理・仮想マイクまでの遅延を別々に測る。
4. 推論例外・エンジン停止・デバイス喪失で原声fallbackしないことを試験。互換や品質が不足すれば採用を見直す。
5. 物理マイク/VRChat/Windows、負荷と長時間試験は別途。PoC合格だけで全機能完成や公開としない。

仕様書§8は「モデル取得はユーザー同意のうえ」と定めているため、モデル取得の同意が必要。
モデル取得の同意と参照音声フォルダーの提示を受領済み。指定フォルダーの14.52秒・48kHz mono PCMを作業用領域へ複製した。
原本は変更せず、音声と元pathはGitへ含めない。実変換試験を進める。

## 原典と調査記録

- [Seed固定engine](https://github.com/jiaheguo521/seed-vc-realtime/blob/58d0ca372cc76f60a798d9f84611f053f9029f3a/realtime_vc_engine.py)と[GPL license](https://github.com/jiaheguo521/seed-vc-realtime/blob/58d0ca372cc76f60a798d9f84611f053f9029f3a/LICENSE)。
- [Seedモデルカード](https://huggingface.co/Plachta/Seed-VC/blob/257283f9f41585055e8f858fba4fd044e5caed6e/README.md)、[HF VADカード](https://huggingface.co/funasr/fsmn-vad/blob/df20e6b30c653645fa4ff125cacfcabd1020a669/README.md)、[FunASR1.2.7配布](https://pypi.org/project/funasr/1.2.7/)。
- [VCClient固定配布一覧](https://huggingface.co/wok000/vcclient000/tree/b03c5379b9a638cf73298641a8048e379befb802)、[Beatrice rc0利用条件](https://huggingface.co/wok000/vcclient_model/blob/c46962577db8cf3fba2b3fc3526af98eb6611840/beatrice_v2_rc0/readme.md)。
- [AISOモデル配布説明](https://huggingface.co/wok000/vcclient_model/tree/c46962577db8cf3fba2b3fc3526af98eb6611840/rvc_v2_chihaya_jinja)。

imozuru2検索役の6query/77hitsと、rootの追加原典追跡は`tmp/voice-resume/research/p2-engine-selection/`。
14引用の照合済みreport/digest、固定metadata7本、モデルカード、公式PyPI archive/sourceとhashを保存。
PyPI archiveは原典を読むために取得しただけで、インストール・import・実行していない。
GitHubの`v1.2.7`タグは404だったため、同名と推測せず公式PyPI固定配布を根拠にした。
