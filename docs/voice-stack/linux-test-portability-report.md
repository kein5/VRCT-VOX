# Linux regression test portability (2026-10-28)

Status: complete for the stated test-portability and Chatbox CLI scope. Base 3064613f.

Research: Kent Beck, [Canon TDD](https://newsletter.kentbeck.com/p/canon-tdd); Martin Fowler, [Test Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html); Michael Feathers, [Characterization Testing](https://michaelfeathers.silvrback.com/characterization-testing); [Python unittest.mock](https://docs.python.org/3.11/library/unittest.mock.html); [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html), including its linked [issue3290](https://github.com/pytest-dev/pytest/issues/3290).

Applied rules: list behaviors; reproduce failure before a product fix; retain regression assertions; patch the lookup boundary with explicit dependencies; keep unit and native integration evidence separate. Python warns that create=True can make nonexistent APIs pass; it is not used as a blanket workaround. No empirical TDD speed/quality effect is inferred from these practice/reference sources.

Research originals and verified reports: tmp/voice-resume/research/linux-test-tdd/. Two search roles completed (40 pooled author hits, 27 official-doc hits); author query attribution is unavailable and recorded rather than guessed. Followed source links for one round; stopped after all five questions had source anchors. Original XP2000 mock paper was not retrieved and is not a decision basis.

## Execution ledger
- Baseline: four affected files, 16 FAIL / 159 PASS / 1 warning, 0.98s. Log: tmp/voice-resume/linux-test-baseline.log.
- Pre-flight: no shared production interfaces between tasks; shared test helper is limited to the Windows test modules.
- Ruling: interpret this request in the context of the 16 failures; preserve Windows-specific native guards and explicitly label emulation — enabling unsupported capture/keyboard operations would require separate implementations and native validation. Cost if broader Linux feature support was intended: those features remain incomplete and visible in the overall ledger.
- Ruling: normal canonical terminal commands use Enter on POSIX — avoids changing terminal modes or adding dependencies. Cost: Linux controls require one additional keystroke.
- Task 1: original Windows test failures reproduced, then fixed test dependency setup without product changes. Targeted 155 PASS / 1 warning (0.63s), including three Linux clipboard/isolation characterizations. An intermediate fixture missed EDataFlow values; the fixture was completed, not the application weakened.
- Task 2 RED: existing three CLI failures plus two new POSIX cases (missing msvcrt); 5 FAIL / 25 PASS. GREEN after POSIX select/read adapter and removing blanket OS guard: 30 PASS / 1 warning (0.04s). Windows key handling covered by five fixture cases; actual POSIX pseudo-terminal covers queued commands/no input, a pipe covers EOF. UDP uses a real ephemeral loopback receiver.
- Task 3: default suite 1222 PASS / 0 FAIL / 6 SKIP / 46 warnings (14.43s). All original 16 tests executed. Twelve tests added; no original case removed or skipped. Added native unavailable-pycaw and Linux panel-guard characterizations. Ruff on all changed Python files and git diff --check pass.
- Final review: fresh independent reviewer found no Critical/Important/Minor issues. Reviewer independently ran 29 CLI cases (excluded UDP from read-only review) and 1,000 PTY sequences, including a command queued after the startup line; all passed. No second review or fix pass was needed.
- Final Ruling: native Windows ABI/console correctness remains an acceptance gate — Linux doubles cannot establish native compatibility; cost: Windows-specific integration defects can remain undetected.
- Final Ruling: native Linux auto-focus/paste, peak selection and panel capture remain outside this test-portability repair — retain explicit guards and the overall feature ledger; cost: those Linux features are still unavailable.
- Final Ruling: VRChat delivery/display and HMD rendering are not newly validated — a private UDP receiver proves packet/log behavior only; cost: application/HMD integration defects require separate acceptance checks.

## Changes and limits

| Area | Linux verification | Native limitation |
|---|---|---|
| Endpoint meter cache (4 original failures) | Real cache code; explicit fake COM imports; reuse, removal, invalidation and peak values | Does not add Linux automatic peak selection or verify Windows COM ABI |
| Clipboard (7) | Isolated Windows branch; focus ordering, detach, key release; Linux copy-only fallback | Linux auto-focus/paste still unsupported; real desktop clipboard not touched |
| VR panel capture (2) | Real invalidation and retry logic with fake GL/capture; fixture resource ownership corrected | Windows screen capture remains Windows-only; no HMD/pixel validation |
| Chatbox CLI (3) | Linux dry-run, noninteractive protection, real terminal input, real OSC packet + Unicode log on private test receiver | No new VRChat delivery/display assertion; Windows console tested via msvcrt double |

No new runtime dependency or license. No audio capture or model access. The remaining skips and warnings predate this change; warnings include openvr/pkg_resources deprecations and telemetry coroutines. Existing feature/native acceptance gates elsewhere in the completion ledger remain open.

Reproduce from repository root:

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python python -m pytest -q
```

In the restricted agent environment, local socket tests require the same approved unrestricted execution used by previous regression runs. This is not a product runtime requirement.
