# Seed-VC offline runtime verification (2026-10-28)

The five consented, hash-pinned models loaded on RTX 4080 SUPER with torch/torchaudio 2.10.0+cu128, torchvision 0.25.0+cu128, Transformers 4.46.3 and FunASR 1.2.7. A permitted local 14.52-second reference produced 12 VAD segment events across 73 chunks. This verifies model load and VAD compatibility, **not voice conversion, perceptual quality, streaming latency, VRChat or Windows**.

[Machine-readable result](seed-vc-load-result.json), [isolated runtime instructions](../../integrations/seed_vc/README.md), [consented artifacts](seed-vc-acquisition.json).

- Input/manifest/state tests: 12 ordinary tests + 2 opt-in actual runtime tests passed; 24 artifact tests passed separately. TDD RED logs are retained locally.
- The real load test ran inside a network namespace with strace: zero AF_INET/AF_INET6 connect attempts, zero host PipeWire/Pulse socket references. Python's IPv6 loopback capability probe attempted a local bind; this is not a model download. No PortAudio module imported. No recording/playback occurred.
- Runtime loaded 143 Seed CFM state entries (including 2 regenerated buffers), 22 length-regulator entries, 937 CAMPPlus, 227 HiFT and 24 VAD; XLSR reports no missing state. Two unused length-regulator and seven unused XLSR checkpoint entries are counted separately.
- Load and VAD timing fields include initialization/tracing overhead and one run only. They are not a performance benchmark.
- Ordinary default suite: 1173 passed, 16 failed, 6 skipped, 46 warnings, 14.31 seconds. Failed-name set exactly matches Task1 baseline. A restricted-sandbox run waited on unavailable services and was interrupted; the reported result is the completed host run under baseline conditions.

## Compatibility decisions

1. Upstream requests torch 2.4 while listing cu128. The isolated runtime uses the [official 2.10/0.25/2.10 combination](https://pytorch.org/get-started/previous-versions/#v2100). The reviewed [2026 weights-only advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p) names 2.10 as a patched version. This is not a full security audit.
2. Full state checking exposed two deterministic Seed buffers. Fixed code and upstream [frequency caching](https://github.com/Plachtaa/seed-vc/commit/1a639856acc60545d777c8680a3612c07cf64b6a) / [position expansion](https://github.com/Plachtaa/seed-vc/commit/c32991ca4ae283b4730a4a5afca7fe39f545d820) justify only the explicit migration in loader.py. Negative tests reject corrupted positions/frequencies and absent/mismatched learned weights.
3. CAMPPlus's [official old-key remap](https://github.com/jiaheguo521/seed-vc-realtime/blob/58d0ca372cc76f60a798d9f84611f053f9029f3a/audio_modules/campplus/DTDNN.py#L113) precedes completeness checking. Colliding renamed keys are rejected.
4. The HF VAD config builds directly without hub alias or remote code. It is a consented alternative, not a claim of identity with ModelScope v2.0.4. Partial pretrained loading is bypassed in favor of strict required-state loading.
5. PortAudio initialization happens at sounddevice import. The local patch defers that import and offers explicit channels for later block tests. Original upstream default behavior is preserved when the optional loader is absent.

imozuru evidence is retained at `tmp/voice-resume/research/p2-seed-runtime/`: 2 queries / 26 hits, 20 primary source files, 9 mechanically checked extracts, report.html and digest.html. Fixed source paths/lines, acquisition hashes and upstream history support the decisions; practical conversion remains the next gate.

## Unchanged default-suite failures

```
FAILED src-python/test/test_active_endpoint_tracker.py::TestMeterCacheManagement::test_disappeared_endpoint_dropped_from_cache
FAILED src-python/test/test_active_endpoint_tracker.py::TestMeterCacheManagement::test_getpeakvalue_failure_invalidates_cache_entry
FAILED src-python/test/test_active_endpoint_tracker.py::TestMeterCacheManagement::test_second_poll_reuses_cached_meter
FAILED src-python/test/test_active_endpoint_tracker.py::TestMeterCacheManagement::test_still_present_endpoint_kept_across_polls
FAILED src-python/test/test_chatbox_sample_player.py::test_dry_run_opens_no_socket_or_log
FAILED src-python/test/test_chatbox_sample_player.py::test_default_noninteractive_launch_cannot_send
FAILED src-python/test/test_chatbox_sample_player.py::test_real_udp_goes_only_to_test_receiver_and_logs_unicode
FAILED src-python/test/test_clipboard_focus_and_paste.py::FocusWindowUsesAttachThreadInputTests::test_attaches_to_the_foreground_threads_input_before_stealing_focus
FAILED src-python/test/test_clipboard_focus_and_paste.py::FocusWindowUsesAttachThreadInputTests::test_detaches_even_if_set_foreground_window_raises
FAILED src-python/test/test_clipboard_focus_and_paste.py::FocusWindowUsesAttachThreadInputTests::test_skips_attach_when_target_thread_is_already_the_foreground_thread
FAILED src-python/test/test_clipboard_focus_and_paste.py::CopyAndPasteAlwaysCopiesTests::test_copies_and_pastes_when_focus_succeeds
FAILED src-python/test/test_clipboard_focus_and_paste.py::CopyAndPasteAlwaysCopiesTests::test_copies_even_when_no_window_can_be_focused
FAILED src-python/test/test_clipboard_focus_and_paste.py::PasteViaCtrlVTests::test_ctrl_is_released_even_if_sending_v_fails
FAILED src-python/test/test_clipboard_focus_and_paste.py::PasteViaCtrlVTests::test_sends_ctrl_v_and_releases_both_keys
FAILED src-python/test/test_overlay_grab_move.py::CaptureJobTest::test_turning_off_drops_the_pending_capture
FAILED src-python/test/test_overlay_grab_move.py::PanelStreamTest::test_failed_start_is_retried_after_turning_on_again
```

No remote push, release, PR or upstream contact. Model weights/private reference remain outside Git. GPL adapter, engine/model license notices and per-dependency distribution obligations require the later packaging review.
