# 設計評価の出典・調査記録

対象: [2026-10-27の設計評価](architecture-evaluation-2026-10-27.md)。コード基準は`1f7900efb705965c32e5dcae1880913763c2ad40`。仕様書3点の原本は`/data/projects/VRCT.cpp/`で読んだ。過去のP1試験は保存済みJSON/CSVとphase reportを参照し、今回再実行したとは扱っていない。

取得した原典の所在・保存表現のSHA-256・時刻・使用スキルのhashは[manifest](architecture-evaluation-source-manifest.json)に記録した。外部資料のmain/master URLは可変であり、hashは保存した文書を識別する。配布バイナリの固定commitや将来のAPI互換性を証明しない。HTMLは本文を変換した表現のhash、PDFは原本と抽出textそれぞれのhashである。

## 1. 調査の範囲と終了理由

問い: 「既存VRCTを維持してspeech.cppとリアルタイムVCを加える際、低遅延・互換性・障害時無音を両OSで成立させる必要十分な境界は何か」。6論点のうち性能・失敗・不足の検証を中心に置いた。

| 論点 | 原典の所在・読む箇所 | 結論の限界 |
|---|---|---|
| Q1 知見はどこにあるか | repoコード、speech.cpp READMEとserver/C API、VC作者README、OS公式文書、CMU SEI | 製品名だけで技術構成を推測しない |
| Q2 現在の待ち・停止・障害伝播 | `src-python/mainloop.py:578,663,690,742`、`controller.py:1017,1036,1244,1252`、`models/tts/tts_scheduler.py`、`models/audio_routing/` | コード上のリスクであり、worker飽和やWindows driver停止を今回再現したものではない |
| Q3 「モデル単体のベンチマークとエンドツーエンド性能を区別」できるか | `sources/speech-qwen.md:79,91`、`sources/seed-readme.md:26,48,135`、repoのmeasurements | 作者値と手元の値を分ける。未測定のUI/VRChat/peer境界を残す |
| Q4 OS・負荷・再接続の前提 | `sources/wireplumber-linking.md:154,172,191`、`sources/pipewire-latency.md:83`、`sources/pipewire-properties.md:573`、Microsoft文書 | consumerの挙動、実period、GPU競合は実機PoCが必要 |
| Q5 code/weight/driverの配布条件 | `NOTICE.md`、speech/Seed license、モデルカード、`sources/gpl-faq.md:1883` | Beatrice採用版や追加vocoder/driverの全artifact条件は未確定 |
| Q6 理論上の評価方法 | ATAM §1.1/7.1〜7.3、QAW §3.8。`sources/atam-original.txt:331`、`sources/qaw-original.txt:584` | lightweightなリスク評価。正式な関係者参加ATAMや定量性能証明ではない |

imozuruの0周で既存evidence mapとコードを起点にし、指定の検索役2本をengine/API系とOS/ATAM系へ分けた。1周ではREADMEからC API・モデル仕様・licenseへ、OS linkingからpriority・clock・latencyへ、ATAMからQAWの6要素へ追跡した。6/6論点に原典と短い引用を対応付けたため区切った。異なる仮説を調べた2本なので、重複率による飽和判定は使っていない。

残る問いは、両OSの実機、版固定VC API、GPU混在負荷、実際に採用するモデル・driverの条件である。資料から性能や接続の成功を補完せず、[PoC](architecture-evaluation-poc.md)へ移した。

## 2. 公式原典の索引

`sources/`は`/tmp/vrct-architecture-review/research/sources/`を指す。第三者の原文全文はローカル閲覧用で、リポジトリへ同梱していない。

| 保存名 | 原典 | 評価に使った箇所 |
|---|---|---|
| speech-readme.md | [speech.cpp README](https://github.com/nyosegawa/speech.cpp/blob/main/README.md) | 全体構成・OS・文書へのリンク |
| speech-server.md | [Server and page](https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md) | task/model数、要求順、PCM形式、Realtime transcription、VAD |
| speech-c-api.md | [C API](https://github.com/nyosegawa/speech.cpp/blob/main/docs/c-api.md) | Requests / Ownership, threads and versions |
| speech-qwen.md | [Qwen3-TTS port](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/qwen3-tts.md) | Speed、first chunkと先頭無音、対応機能 |
| speech-irodori.md | [Irodori port](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/irodori-tts.md) | 文単位生成、voice、長文・licenseの違い |
| speech-license.md | [speech.cpp LICENSE](https://github.com/nyosegawa/speech.cpp/blob/main/LICENSE) | MIT |
| vcclient-readme.md | [VCClient README](https://github.com/w-okada/voice-changer/blob/master/README.md) | edition/OS/model表 |
| vcclient-legacy-api.md | [旧REST処理](https://github.com/w-okada/voice-changer/blob/master/server/restapi/MMVC_Rest_VoiceChanger.py) | POST /test、base64 s16LE。現v2契約へ一般化しない |
| vcclient-notice.md | [LICENSE-NOTICE](https://github.com/w-okada/voice-changer/blob/master/LICENSE-NOTICE) | 別vocoder・Beatrice条件への参照 |
| seed-readme.md | [Seed-VC-Realtime](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/README.md) | Latency / A/V measurement / Performance表の条件差 |
| seed-engine.md | [RealtimeVCEngine](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/realtime_vc_engine.py) | デバイス所有、start/stop、fallback。取得コードは実行していない |
| seed-license.md | [Seed LICENSE](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/LICENSE) | GPLv3 |
| seed-model.md | [Plachta/Seed-VC](https://huggingface.co/Plachta/Seed-VC) | カードmetadataのgpl-3.0 |
| irodori-card.md | [Irodori Small MF](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small-MF) | License & Ethical Restrictions |
| qwen-card.md | [Qwen CustomVoice 0.6B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) | 対象weightのlicenseと機能。portとは別 |
| wireplumber-linking.md | [Linking Policy](https://pipewire.pages.freedesktop.org/wireplumber/policies/linking.html) | streamへのtarget/fallback/reconnect指定 |
| wireplumber-priorities.md | [Node priorities](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/priorities.html) | 相対順位とユーザーdefault |
| pipewire-loopback.md | [Loopback](https://docs.pipewire.org/page_module_loopback.html) | virtual sink/source |
| pipewire-properties.md | [pipewire-props](https://docs.pipewire.org/page_man_pipewire-props_7.html) | scheduling / clock / resampler |
| pipewire-latency.md | [Latency support](https://docs.pipewire.org/page_latency.html) | Linked nodes / Async nodes |
| portaudio-callback.md | [Writing a callback](https://www.portaudio.com/docs/v19-doxydocs/writing_a_callback.html) | callbackで避けるblocking/割当等 |
| windows-exclusive.md | [Exclusive-Mode Streams](https://learn.microsoft.com/en-us/windows/win32/coreaudio/exclusive-mode-streams) | shared低periodと共存、session volumeの適用範囲 |
| windows-low-latency.md | [Low Latency Audio](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio) | buffer/engine/driver、IAudioClient3 |
| windows-process-loopback.md | [Application loopback sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/) | process tree capture、build 20348条件 |
| atam-original.pdf / .txt | [ATAM: Method for Architecture Evaluation](https://www.sei.cmu.edu/documents/629/2000_005_001_13706.pdf) | §1.1、§7.1〜7.3 |
| qaw-original.pdf / .txt | [Quality Attribute Workshops, Third Edition](https://www.sei.cmu.edu/documents/716/2003_005_001_14249.pdf) | §3.8、冊子p.11、PDF p.23 |
| gpl-faq.md | [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html#MereAggregation) | MereAggregation |

VCClient NOTICEとSeedモデルカードは完全な原文が短いため、fetch.pyの最低文字数検査で除外された。その後、plaintextを別経路で確認・保存し、`manual-fetch-log.jsonl`に記録した。取得失敗を実体の不在と扱っていない。GNU FAQはWebツールではtimeout、原典保存用の取得では成功した。

## 3. 使用スキルと適用範囲

| スキル | 読んだSKILL.md | 適用 |
|---|---|---|
| imozuru | `/home/kei/Documents/projects/it-duo/.agents/skills/imozuru/SKILL.md` | 6論点、2方向の探索、原典の後方追跡・保存・照合、停止理由 |
| software-architecture-analysis | [公開原本](https://github.com/magnus919/agent-skills/blob/main/software-architecture-analysis/SKILL.md) | 既存構造、事実分類、依存・所有・実行時境界の分析 |
| software-architecture | [公開原本](https://github.com/magnus919/agent-skills/blob/main/software-architecture/SKILL.md) | シナリオ、3案の比較、失敗時契約、段階移行とfitness evidence |
| voice-latency-audit | [ユーザー指定原本](https://github.com/RobStrayer/voice-agent-skills/blob/main/plugins/voice-foundations/skills/voice-latency-audit/SKILL.md) | 時刻境界・clock・重なり・成功/失敗群・可聴性・停止の監査 |
| adr-authoring | [公開原本](https://github.com/magnus919/agent-skills/blob/main/adr-authoring/SKILL.md) | proposed状態、代替案、却下理由、反証条件、責任と検証リンク |
| Superpowers / brainstorming | `/home/kei/.codex/plugins/cache/openai-curated-remote/superpowers/7.0.1/skills/brainstorming/SKILL.md` | 実装前の代替案提示と設計、独立Builder Check |

外部から読んだ4スキルは`/tmp/vrct-architecture-review/skills/`に保存し、インストールしていない。voice-latency-auditのLiveKit/Twilio固有フィールドをVRCTへ当てはめず、現コードと保存traceに対応する境界の監査へ適用した。今回は修正・実験の依頼ではないため、同スキルの修正後実験はPoC設計に留めた。

Builder Checkでは「TTS取消と全体muteの範囲・再開条件」が指摘された。TTSの独立継続契約と全体muteの保持を3文書へ反映し、再レビューで重大な未解決事項なしとの回答を得た。これは実装成功の保証ではない。

## 4. ローカル調査成果物と制約

- [原典の抜粋・照合済みHTML](/tmp/vrct-architecture-review/research/report.html)
- [原典の補助解説HTML](/tmp/vrct-architecture-review/research/digest.html)
- [論点と原典のmap](/tmp/vrct-architecture-review/research/map.md)
- [取得・停止のlog](/tmp/vrct-architecture-review/research/log.md)

抜粋6件と補助解説の全引用を、imozuruのreport.py/digest.pyで保存原文と照合した。最初の照合ではファイルの相対指定とPDFの改行カウントに誤りがあり、修正後に成功した。

**検索全ヒットのHTML台帳は未作成。** 2検索役の全ヒットJSONは会話内で受領したが、HTMLへの取込は行っていない。engine側3検索35件、OS/ATAM側7記録180件で、後者先頭は4検索の統合結果。個々のqueryへの帰属を捏造したり、採用資料だけに絞って全検索結果と称したりしていない。HTMLは原典の取得記録と抜粋を示す補助資料で、imozuruの完全な検索アーカイブとは区別する。

一時保存の原典・HTMLは`/tmp`の消去で失われ得る。再調査用の原典URL・hash・設計判断はリポジトリに残す。今回起動した調査用処理は終了を確認した。既存の音声serverや仮想マイクは変更していない。

## 5. 今回の検証

`uv run --no-project python`による文書検査で、Markdown 5ファイルのローカルリンク37件、原典34表現のhash、6スキルのhashを確認し、エラー0。Mermaid 4図はfence・subgraphの静的確認のみで、描画器によるrender検証はしていない。`git diff --check`と新規Markdownの空白検査も通過した。

製品コード・依存・音声設定を変更していないため、アプリのテストsuiteと実機測定は再実行していない。既存83 PASSなどは過去の記録として評価書に引用し、今回の検査結果に合算していない。
