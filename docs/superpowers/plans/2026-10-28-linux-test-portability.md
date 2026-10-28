# Linux test portability plan

Spec: ../specs/2026-10-28-linux-test-portability.md
Base: 3064613f
Inline execution; one final fresh review of this change, one fix pass for important findings. Preserve workspace because the overall feature implementation remains active.

## Task 1: Windows behavior tests on Linux
Files: src-python/test/platform_test_support.py, test_active_endpoint_tracker.py, test_clipboard_focus_and_paste.py, test_overlay_grab_move.py.
Baseline: 16 failed / 159 passed in all four affected files.
Use an isolated import with explicitly supplied OS dependencies for import-time Windows branches. Keep real application logic. Patch module-local OS reference only for GL initialization; initialize the stream retry fixture consistently with its pre-existing fake GL resources. Add native Linux fallback assertions without touching the desktop.
Expected: these three files pass on Linux; existing Windows logic and native guards unchanged.

## Task 2: Chatbox Linux behavior
Files: tools/chatbox_sample_player.py, src-python/test/test_chatbox_sample_player.py.
Existing failing dry-run, launch protection and actual UDP tests are RED. Add a real POSIX pipe/terminal input test for P/Q/R + Enter, observe missing msvcrt path, then implement the smallest OS-specific keyboard adapter. Keep Windows msvcrt behavior tested and unchanged. No new dependencies.
Expected: all four files pass. Test destination is an ephemeral loopback socket, never 9000.

## Task 3: Verification and report
Run bare pytest using uv and existing Linux env; run changed-file Ruff and git diff --check. Record research provenance, test counts, remaining native integration gates, update completion ledger. Fresh review only of this plan's changes, then one RED→GREEN fix pass if needed.

Review focus: isolated import leaks; mock expectations hiding actual code; Windows import compatibility; terminal blocking/buffering/EOF; accidental OSC/log side effects; preservation of Linux unsupported-feature guards; no test skipping to conceal the original failures.
