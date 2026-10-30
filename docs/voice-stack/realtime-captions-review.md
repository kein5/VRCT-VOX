# Realtime字幕接続の独立レビュー

範囲: `1ac9eb46..15b0a356`。fresh reviewerによる1回のread-only review。
Critical 0、Important 4、Minor 1。実装者はImportant 4件を採用し、1回のRED→GREEN修正passを実施した。再レビューは行っていない。

| 指摘 | 対処・再現試験 |
|---|---|
| フィルターに一致したfinalが常時process.logへ保存される | `/run/word_filter`もIPCのみとし、本文付きUI通知を保って常時保存を止めた。実Controller→実response loggerで1 RED→GREEN |
| 描画後guardで拒否したfinal/訳文が履歴に残り、停止cleanupや別source更新で再表示される | 描画前の有界状態を保持し、拒否/例外時に戻す。直前の公開済みfinalは保持し、pendingと拒否画像を無効化。partial/final/translated×cleanup/別sourceの6ケース中5 RED→6 GREEN |
| legacy録音の停止timeoutを成功と誤認してRealtimeを開始できる | `stopCaptureForRealtime`で両legacy機能を一度に停止。未完了cleanup workerを保持し、完了確認まで新取得を拒否。stop例外は成功と扱わずアプリ再起動までhandoff拒否。Controller 2件と実session/模擬cleanup 6件がRED→GREEN |
| 停止済みRealtime owner参照が残り音量メーターを再開できない | requestedがOFFならownerを有界時間でdrainし、完了時のみlegacy energy取得を許可。busy継続拒否/終了後許可を両sourceで2 RED→GREEN |

最終関連 **55 PASS**（1.87秒）。音声全回帰 **568 PASS/7 Seed opt-in SKIP/2 warnings**（56.97秒）。
標準suite **1194 PASS/16既知FAIL/6 SKIP/46 warnings**（14.60秒）、変更前と失敗名が完全一致。変更PythonのRuff/diff check PASS。
実アプリ受入れも **1 PASS/25.15秒**。実Tauri/全Model/ASR/VAD/private音声とHTTP翻訳fixtureによる範囲は[報告](realtime-captions-report.md)のとおり。

## 原典照合

imozuruで2検索役を使い、固定forkのstopper→source contextとCPythonのjoin→内部wait/exceptionへ1周たどった。
[固定forkのstopper](https://github.com/misyaguziya/custom_speech_recognition/blob/afae7ff78cd5da36e864122f16972d2b0044e03f/speech_recognition/__init__.py#L838)は`wait_for_stop=True`でlistenerの終了を待つ。
[CPython 3.11.17 join](https://github.com/python/cpython/blob/v3.11.17/Lib/threading.py#L1087)ではtimeout後に生存確認が必要で、[bootstrap](https://github.com/python/cpython/blob/v3.11.17/Lib/threading.py#L1044)は正常終了と例外終了の両方でthreadを終了する。
したがって外側の停止threadを保持し、正常完了を別途記録する。任意ドライバの物理解放をこれだけで保証するものではない。

原典raw2ファイル・SHA256・map/log・照合済み抜き書き8件とdigestは`tmp/voice-resume/research/realtime-handoff/`。
固定forkは導入済みファイルと全byte一致。検索役のWeb抽出行番号は誤りがあったため、rootが保存原文の物理行番号へ修正した。
検索役の全検索hitsは未回収のため、その検索記録の網羅性は主張しない。取得URLと判断根拠は保存済み。両検索役は終了しており、未解決の実装障害は残っていない。

## 保留とレビュー範囲の判断

Minor保留: 全sourceでrequested=Falseになるとstate pollが止まり、cleanup中の「Stopping captions」表示が残る場合がある。
開始ボタンはrequestedで制御され、再開始自体は可能なためMinor評価を維持した。進行中のcleanupが実際に残る場合はbackendが開始を拒否する。

- 過去にレビュー済みのREST/WS/Ingress/native capture内部は重複レビューしない。ただし今回のlegacy handoff境界は修正対象とした。
- Realtime小overlay、物理遅延、実MT品質/速度、HMD、Windows、長時間混在負荷、native legacy録音への切替は未検証を維持する。
- JSONにできない任意payloadのgeneric error dumpは今回の生成経路では再現条件がない。新Realtime payloadは検証済みprimitiveで構成するため、独立の今回指摘とはしない。将来payload型を増やす際は再評価が必要。
- 翻訳historyは既存の会話共通contextで、入力本文と言語は各呼出しに渡る。別sourceの結果取り違えは確認されず、広いtranslator再設計はしない。共有CTranslate2による待ち時間と期限切れはあり得る。
- P4 mic訳文発声、実VC製品統合、配布・ライセンスは後続工程。現段階を全機能完了とはしない。

継続作業のため`frail-walrus`と工程ledgerを保持する。merge/push/PR/上流連絡は実施しない。

## 工程内の判断記録

- Ruling: choose dedicatedRealtime session and settings (candidateB), not legacy phrase/VAD reuse or duplicate translator — compatibility and avoiddoubleVAD — cost additionalcontrols/ownership boundary.
- Ruling: preserve existingexecution method and proceed without repeateddesignapproval — userexplicitly requested closed-loop implementation until allfeatures — cost choices need documented revisability.
- Ruling: source-specific dedicatedsession owners with boundedupdate queue; finaltranslation separated later — avoid blockingWS with translation — cost several boundedworkerthreads instead of one sharedloop.
- Ruling: latency/frameinvalid remains stop/reselect; no automaticreconnect — privacy/sourceidentity preservation — cost manualrecovery on validgraphchanges.
- Task 1: Ruling: add PipeWireCapture.request_stop to invalidate capture startup synchronously without join/driverIO — closes stop/start race for IPC caller — cost an explicit two-stage shutdown API; stop remains cleanup boundary.
- Task 1: Ruling: state includes stopping until owner thread has exited — closed must not imply resources gone before join — cost callers handle transitionalstate.
- Task 1: Ruling: localhost canonicalized to127.0.0.1 by existinglocal_url is valid, noDNS; testreject expectation was wrong — preserve shared helper behavior — cost inputalias accepted but stored/transport URLnumeric.
- Task 2: Ruling: carry monotonic received_ns from WS acceptance through session/delivery, expire at receipt+2s — include upstream mailbox dwell, never renew stale finals — cost timestamp is transport receipt, not acoustic E2E; field default0 preserves pure reducer/equality and fake sessions stamp on consumption.
- Task 2: Ruling: add generation to caption events alongside namespace — frontend can reject a late IPC write after stop without making fast stop wait on stdout — cost UI must enforce generation as well as namespace; already issued external side effects cannot be undone.
- Task 2: Ruling: retain one busy session/delivery pair per source and reject restart until drained — bound noncooperative translation workers instead of abandoning unlimited threads — cost user must wait for blocked provider or restart process.
- Task 2: Ruling: use existing Controller lifecycle locks/short state lock rather than introduce generic coordinator — minimal added boundary for two sources — cost Controller grows; extraction remains possible after behavior stabilizes.
- Task 2: Ruling: extract side-effect-free _initRealtimeASR and call it in two existing __new__ fixtures — new dependency must exist in deliberately partial test instances, no runtime bypass of mutual exclusion — cost fixtures know the initialization boundary.
- Task 2: Ruling: energy start returns bool and legacy threshold toggles reflect refusal while Realtime owns source — prevents duplicate capture and misleading ON display — cost same-source legacy meter unavailable until Realtime cleanup.
- Task 2: Ruling: explicit ASR language maps through existing transcription table (exact locale then Whisper code) to translator display-name API; unknown mapping rejects start — do not infer detected language — cost future ASR codes require table extension.
- Task 3: Ruling: endpoint list response includes source and model list includes base_url — prevent independent source responses crossing and stale server model metadata use — cost additive IPC fields and controller-test expectations.
- Task 3: Ruling: UI compares generation/namespace/revision with synchronous Jotai store reads, keeps <=256 retired IDs and prunes only pending rows on stop — events in one batch must not use stale React closures — cost small in-memory replay ledger alongside existing logs.
- Task 3: Ruling: same-generation terminal state cannot return to ready; settings response locally invalidates affected pending captions before later statepoll — reject delayed snapshots after failure/configchange — cost transitional stopping UI until authoritative newer state.
- Task 3: Ruling: overlay callback stays on delivery workers, on_stopped runs in reader finally rather than fast-stop receiver — no driver/render wait in prioritystop — cost visible pending cleanup waits for any already-running renderer; close reports worker stillbusy.
- Task 3: Ruling: Realtime rendering uses large overlay with pending/history identity, shared Model lock and render revision; legacy small overlay retains its existing provider behavior — required caption history supported without duplicating small-log ownership — cost Realtime users enable large overlay; UI states this scope.
- Task 3: Ruling: add callback deadline metadata (expires_ns) to delivery so post-render guard still enforces receipt+2s — slow renderer cannot publish expired translated output — cost monotonic metadata is backend clock, not browser clock or acoustic timing.
- Task 4: Ruling: no local translation weights under product weights dirs or HF cache; use deterministic loopback OpenAI-style response through real LMStudio provider to verify final-only adapter/delivery; no new model download — preserves download consent and separates component acceptance from real MT quality — cost actual translation quality/latency remains a later gate, not reported as realMT E2E.
- Task 4: Ruling: do not activate legacy host recorder merely to prove switch-back, because user approved existing syntheticinput only and private_graph does not isolate hostPulse/ALSA — cover legacy mutual exclusion by Controller tests and verify native realtime OFF/restored choices — cost physical legacy switch-back remains untested until fully private legacy route or recording consent.
- Task 4: Ruling: allow a connected selected external translator when CTranslate2 status is unavailable; retain existing warm fallback path when local model is available — external inference must not require unapproved local translation weights, and existing fallback users keep behavior — cost missing local fallback still cannot recover an external translation failure; existing error reporting remains.
- Final: Ruling: prior transport/capture internals stay outside re-review; new legacy handoff defect is in scope despite underlying legacy timeout behavior — fixes ownership boundary without recreating old plans — cost older independent defects remain possible.
- Final: Ruling: large-only overlay and native legacy switch-back/realMT/physical/HMD/Windows/load gates remain disclosed — no evidence to claim them verified — cost follow-up acceptance still required.
- Final: Ruling: generic unserializable response dump is deferred outside this change because production caption payloads contain validated JSON primitives; filtered-final persistence is fixed separately — no invented exploit claim — cost a future unsupported payload type needs renewed review.
- Final: Ruling: shared translation history/client concurrency has no demonstrated source-crossing bug in this range; preserve existing conversation context and CT lock — avoid unrelated translator rewrite — cost contention can expire translated results, already bounded and unmeasured under mixedload.
- Final: Ruling: retain cleanup worker refs across all legacy stops and add a dedicated all-feature handoff API; a caught stop exception keeps handoff blocked until application restart — thread termination alone does not certify successful stop — cost no automatic retry after ambiguous cleanup failure. Existing reconfigure behavior is otherwise retained.
- Final: Ruling: rejected overlay render rolls back bounded history/revision state and retires pending identity; earlier published final remains — cleanup/other source cannot publish invalidated text — cost bounded deepcopy per realtime render; mixed-load cost not yet measured.
- Final: Ruling: preserve worktree/ledger and continue next feature; no merge/push/PR/menu — user closed-loop authorization and upstream restriction persist — cost full branch still has known P5 failures and is not release-ready.
