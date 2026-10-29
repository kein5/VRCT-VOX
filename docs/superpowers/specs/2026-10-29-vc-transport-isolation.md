# Isolate the VC audio transport from the application interpreter

The mixed RVC/ASR/TTS trial reproduced `vc_capture_overrun` and
`vc_block_expired`. An opt-in timestamp probe observed a generation-2 collection
lasting 98.59 ms in the application, followed by burst delivery into the bounded
VC queue. Worker responses before the pause were about 20–37 ms. Thread limits
matching upstream RVC did not resolve the mixed-load failure.

Choose a small, separately executed transport process, reusing VCProcess and its
existing capture/inference/output checks. The application exchanges only one
bounded configuration request and periodic bounded health reports. Original vs
converted selection, source identity, generation and global OS gate stay intact.
The existing Linux supervisor gains fixed router-module/frozen-entry variants;
creator-thread/parent/supervisor death must terminate the entire chain.

Alternatives rejected: disabling/freezing application-wide GC can retain cycles;
increasing buffers or deadlines does not isolate unrelated application pauses.
Replacing all transport with new native DSP is unnecessary for this defect.

Preserve 48 kHz mono S16, 80 ms blocks, one unsent complete block, the 160 ms
block-end freshness limit and cancellation at OS writes. No raw fallback or
automatic restart. Stop closes the control pipe and reaps the owned process;
failure to finish cleanup remains visible. No speech/model data in health IPC.
The router uses the application interpreter, not a new downloaded runtime.

Acceptance: force a 350 ms application GIL hold with fake inference and private
synthetic audio; converted output and child processing must survive while Stop
and owner death still remove them. Then repeat real mixed and sustained trials.
This does not guarantee immunity to OS/GPU starvation or long router-local GC.
Linux implementation first; frozen entry covered without claiming a tested
Windows package. External-inference architecture B remains the boundary.
