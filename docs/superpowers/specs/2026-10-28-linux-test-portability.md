# Linux test portability

User request: Linuxにも適用できるように修正してほしい。imozuruでTDDのベストプラクティスを調べてから。

Scope is the 16 failures just discussed: preserve their regression assertions, execute them on Linux, and make the OS-independent Chatbox CLI work on Linux. This does not claim native Linux implementations of Win32 focus/key injection, COM peak tracking, or Windows panel capture. Existing Linux clipboard fallback and unsupported-platform guards must remain testable. Native Windows validation remains separate.

Research completed before product edits: `tmp/voice-resume/research/linux-test-tdd/{map.md,log.md,report.html,digest.html}`. Followed Fowler→Beck and pytest→issue3290, saved six originals, verified quotes. No quantitative TDD effectiveness claim.

Acceptance:
- The original 16 cases run and pass, with no skip/xfail added to them.
- Windows dependencies are replaced only within the tested module; never change process-wide sys.platform/os.name or load real Windows DLLs during these unit tests.
- Cache retention/invalidation, focus attach/detach, Ctrl release, capture invalidation and stream retry assertions remain meaningful.
- Linux Chatbox supports dry-run and explicitly started loopback UDP. Interactive Linux commands use a normal line-buffered terminal (P/Q/R + Enter); no terminal mode or global keyboard changes.
- Without --start a noninteractive invocation cannot send. Dry-run opens no socket/log. Tests never send to VRChat port 9000.
- Run the default Python suite, targeted suite and changed-file lint. Report hardware/OS limitations and pre-existing warnings.

No new dependencies, model downloads, recording, remote publication, upstream contact, or PR.
