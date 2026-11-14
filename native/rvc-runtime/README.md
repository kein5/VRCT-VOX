# rvc-runtime

Inference-only RVC voice conversion in Rust (issue #275, Phase 1: offline conversion).
The processing follows the specification in
[`docs/superpowers/specs/2026-11-15-rvc-inference-runtime-design.md`](../../docs/superpowers/specs/2026-11-15-rvc-inference-runtime-design.md).

This crate stands alone. The application does not use it yet: nothing under `src-tauri`
or `src-python` refers to it, and the existing external RVC runtime is unchanged.
Integration is Phase 3; streaming is Phase 2.

## What it does

| Stage (spec section) | Where | How |
|---|---|---|
| Voice model `.pth` (3.1, 3.2) | `src/pth.rs`, `src/model.rs` | Reads the zip + pickle checkpoint directly. The pickle reader only knows tensors, lists, dicts and numbers and refuses anything else, so a model file cannot run code. Half-precision weights are widened to `f32`. |
| Index `.index` (3.3, 7) | `src/index.rs` | Reads FAISS `IVF…,Flat` (what training writes) and flat L2 files; searches the `nprobe` closest lists like FAISS does. A trained-but-empty index is refused. |
| Input filter (4) | `src/filter.rs` | Fifth-order Butterworth high-pass at 48 Hz, applied forward and backward. |
| Splitting long input (4) | `src/pipeline.rs` | Cuts at the quietest point near every interval, with reflected padding. |
| F0 (5) | `src/f0.rs`, `src/backend.rs` | Log-mel front end and salience decoding here; the RMVPE network runs on ONNX Runtime. Extractors sit behind the `F0Estimator` trait. |
| HuBERT features (6) | `src/backend.rs` | ONNX Runtime; one graph gives both the v2 (768) and the v1 (256) features. |
| Blend, protect, ×2 (7, 8) | `src/index.rs`, `src/pipeline.rs` | |
| Synthesizer (9) | `src/synth.rs`, `src/onnx.rs` | The VITS + NSF network is built as an ONNX graph from the model's own weights at load time, for v1/v2, with or without F0, at any upsampling layout. |
| Noise and seed (9.2, 13.2) | `src/noise.rs` | All randomness is generated here and fed to the graph, so a seed fixes the output. |
| Loudness mix, resampling, peak limit (10) | `src/audio.rs` | |

Not implemented in Phase 1: the streaming window interface (9.3, 12), formant shift, and
F0 extractors other than RMVPE.

## Assets

The two fixed networks are data, not code, and are not part of this repository.

| File | Source | Licence |
|---|---|---|
| `rmvpe.onnx` | `lj1995/VoiceConversionWebUI` on Hugging Face (pinned revision and SHA-256 in `reference/setup_reference.py`) | MIT |
| `hubert.onnx` | Exported by `reference/export_hubert_onnx.py` from the Transformers-format `hubert_base` of the same repository, with the stock `transformers.HubertModel` | MIT (repository); the upstream ContentVec/HuBERT terms must be confirmed before bundling (spec section 14) |

Bundling them with the application, and recording their final source and licence in
`NOTICE.md` and the licence ledger, belongs to Phase 3.

## Use

```sh
cargo run --release --bin rvc-infer -- \
  --model voice.pth --index voice.index \
  --hubert hubert.onnx --rmvpe rmvpe.onnx \
  --input in.wav --output out.wav --seed 1
```

`--seed` makes the output reproducible; without it every run draws new noise, like the
reference. `rvc-infer` prints timings only. The library reports errors without audio or
text content, and nothing in it logs samples.

ONNX Runtime is downloaded by the `ort` crate at build time. `--features cuda` selects the
CUDA provider (not measured yet).

## Verification

`cargo test` runs two groups:

- **Unit and offline tests** need nothing but the repository. `tests/data` holds tiny
  voice models with random weights, the reference's output for them and a small FAISS
  index (written by `reference/make_test_data.py`; no trained weights, no recordings).
- **Conformance tests** (`tests/conformance.rs`) compare against the reference
  implementation and report themselves as skipped until the fixtures exist.

To reproduce the conformance run (about 2.6 GB under `~/.cache/vrct-vox/rvc-reference`,
or `RVC_REFERENCE_DIR`; needs `uv`):

```sh
python native/rvc-runtime/reference/setup_reference.py          # pinned engine, weights, model, clip, venv
REF=~/.cache/vrct-vox/rvc-reference
$REF/venv/bin/python native/rvc-runtime/reference/export_hubert_onnx.py
$REF/venv/bin/python native/rvc-runtime/reference/dump_reference.py
cd native/rvc-runtime && RVC_REQUIRE_REFERENCE=1 cargo test -- --nocapture   # METRIC lines
```

What is downloaded, all pinned by SHA-256:

- the reference engine at the commit the application already pins (`81eed5e8…`), run on
  the CPU in single precision;
- a real v2 / 48 kHz / F0 voice model with its index: *Saisho Utane* (CC BY 4.0), the
  model in the application's catalogue;
- a real v2 / 40 kHz / F0 model: the published `pretrained_v2/f0G40k.pth` base generator
  (MIT), saved as an inference model by `dump_reference.py` with its weights unchanged;
- a 3.4 s speech clip from the VOiCES corpus (CC BY 4.0), 16 kHz mono, used by the
  conformance tests, and a 7 s LibriSpeech utterance (CC BY 4.0) for the listening set;
- random-weight models for v1/v2 × F0/no-F0 × 32/40/48 kHz, generated locally.

The reference is driven as a black box: the scripts call its public entry points and
record the values that cross them.

### Results

Measured on 2026-11-15, Linux, AMD Ryzen 9 9900X, CPU execution, ONNX Runtime 1.31 via
`ort` 2.0.0-rc.15, reference on PyTorch 2.11.0 (CPU, fp32). These are measurements of
this machine, not guarantees.

| Check (spec 13.1) | Result |
|---|---|
| Input filter and padding | max abs error 2.8e-8 |
| HuBERT features, v2 / v1 | relative error 1.8e-6 / 1.7e-6, cosine similarity 1.0000000 (min over frames) |
| RMVPE F0 | voicing agreement 100 % (941 and 5271 frames); cents error mean 0.016, max 0.08 (max 4.5 on the long input) |
| Quantised pitch from the reference F0 | identical |
| Quantised pitch end to end | 1 of 941, 0 of 941, 0 of 5271 frames differ, never by more than one step |
| Index search (88 024 vectors) | same neighbours in the same order in 469 / 469 frames; distance relative error ≤ 4.9e-7 |
| Blended features | relative error 9.0e-8 |
| Synthesizer input features, end to end | relative error ≤ 1.9e-6 |

| Check (spec 13.2) | Result |
|---|---|
| Synthesizer, noise off, reference inputs: trained v2 48 kHz / 40 kHz | SNR 89.6 – 91.0 dB / 86.1 dB |
| Same, random weights (v1/v2, F0/no-F0, 32/40/48 kHz) | SNR 122 – 132 dB |
| Whole pipeline, noise off, random weights | SNR 70 – 97 dB |
| Whole pipeline, noise off, trained models | SNR 13 – 18 dB sample by sample; 86 – 91 dB once the reference's pitch track is substituted (see below) |
| Long input (110 s, split thresholds 1/6/38/41 s) | same cut position and piece lengths as the reference |
| Loudness mix 0.25 + resampling 48 → 44.1 kHz on the reference's synthesizer output | SNR 81.7 dB |
| Seeded noise | same seed gives identical samples; another seed changes them |
| Seeded noise, log-spectral distance to the reference | 6.91 dB and 7.90 dB, against 6.87 dB and 7.97 dB between two seeds of the reference itself |
| Seeded noise, F0 of the output against the reference's output | voicing agreement 98.8 % / 95.6 %, mean cents error 4.2 / 5.6 (reference against itself: 98.8 % / 99.1 %, 5.8 / 5.4) |

On the trained-model line: a trained source filter follows the excitation phase, and the
phase is the integral of the pitch. Our F0 differs from the reference's by 0.016 cents on
average, which is enough to move the waveform: shifting the *reference's own* pitch input
by 0.02 cents drops its SNR against itself to 10 – 15 dB. With the reference's pitch track
and our own features the output agrees to 86 – 91 dB. So the remaining sample-level
difference is that pitch difference, not the synthesizer.

The 40 kHz output F0 agreement (95.6 % against 99.1 %) looked worse than the reference's
own seed-to-seed spread with a single seed. Measured over four seeds in the objective
comparison below, it is within that spread.

**Listening (spec 13.2), 2026-11-15:** the maintainer listened to the four public cases
below in a browser and could not tell the Rust output from the reference; all four were
judged the same voice and phrasing. ABX trial counts were not recorded.

**Not verified:** listening with v1, 32 kHz or F0-less models (no public model was
available, see below); performance against the current external runtime (13.3) has
not been measured; fp16 and CUDA have not been run; no real v1, 32 kHz or F0-less voice
model was available, so those variants are verified with random weights and, for v1, the
HuBERT v1 features.

### Listening comparison (spec 13.2)

The numbers above cannot stand in for listening. `reference/make_listening_set.py`
prepares a blind comparison:

```sh
$REF/venv/bin/python native/rvc-runtime/reference/make_listening_set.py
# your own models and recordings (kept local, never uploaded or committed):
$REF/venv/bin/python native/rvc-runtime/reference/make_listening_set.py \
  --voice my_v1.pth my_v1.index --voice my_32k.pth --input me.wav --transpose 0 --transpose 12
```

For every model and input it converts the same 16 kHz audio three times with the same
settings: the reference with two different noise seeds and this runtime. It then writes
`$REF/listening/index.html`, an ABX page (Japanese) with the audio embedded in it. Open
it in a web browser; an editor's built-in preview may show the page without playing
sound. `--page-only` rebuilds the page from an existing set without converting again.

- Each trial plays A, B and X, where X repeats one of the two, and asks which. Which
  pair is on screen and which side is the reference are hidden and random.
- Half of the trials are the control "reference against reference with another seed".
  Synthesis noise makes any two runs differ a little, so the control shows how well
  that alone can be heard; "reference against Rust" is read against it.
- After the trials, each model gets the specification's question: do the two sound like
  the same voice with the same phrasing?
- The result (correct answers per pair with a binomial p value, and the judgements) can
  be saved as JSON for the pull request.

Without arguments the set holds the two public models and two public clips (the VOiCES
clip and a LibriSpeech utterance, both CC BY 4.0): four cases, 48 trials. The
specification asks for v1/v2, 32/40/48 kHz and with/without F0; the public set covers v2
with F0 at 40 and 48 kHz only, so the other variants need models passed with `--voice`.

### Objective comparison

`reference/objective_compare.py` measures what the listening test asks, with models
pinned in `setup_reference.py` (about 1.4 GB more):

| Question | Measure |
|---|---|
| Same voice? | speaker-embedding cosine similarity (SpeechBrain ECAPA-TDNN, VoxCeleb; Apache-2.0) |
| Same phrasing? | character error rate between Whisper-small transcripts (Apache-2.0), and against the input's transcript |
| As natural? | TorchAudio-Squim subjective MOS estimate |
| Same timbre? | MFCC distortion (mel-cepstral distortion formula on MFCCs), log-spectral distance |
| Same intonation? | F0 voicing agreement and pitch difference in cents (RMVPE) |
| Same level? | RMS level difference |

Synthesis noise is random, so every model and input is converted with four seeds by
both implementations. A measure passes when "runtime against reference" is no further
apart than the reference's own seeds are from each other (for the per-output measures:
the runtime's mean lies within the reference's range widened by half of it).

```sh
$REF/venv/bin/python native/rvc-runtime/reference/objective_compare.py --language en
# your own models and recordings (kept local):
$REF/venv/bin/python native/rvc-runtime/reference/objective_compare.py --voice my.pth my.index --input me.wav --language ja
```

It writes `$REF/objective/report.md` and `report.json`. Transcripts are only used for
the error rates and are neither printed nor stored.

Results (2026-11-15, same machine, CPU; the two public models × the two public clips,
seeds 7–10). Each cell gives the lowest and highest per-case mean over the four cases.

| Measure | Reference against reference | Runtime against reference | Within the spread |
|---|---|---|---|
| Speaker similarity (cosine) | 0.915 – 0.965 | 0.915 – 0.970 | 4 / 4 |
| CER between transcripts | 0.000 – 0.036 | 0.000 – 0.027 | 4 / 4 |
| MFCC distortion | 21.616 – 30.184 | 21.556 – 30.430 | 4 / 4 |
| Log-spectral distance (dB) | 7.031 – 7.936 | 7.044 – 7.933 | 4 / 4 |
| F0 voicing agreement | 0.948 – 0.989 | 0.947 – 0.990 | 4 / 4 |
| F0 difference (cents, median) | 2.504 – 2.857 | 2.444 – 2.894 | 4 / 4 |
| Level difference (dB) | 0.099 – 0.338 | 0.088 – 0.361 | 4 / 4 |
| Squim MOS estimate | 3.760 – 4.450 | 3.741 – 4.426 | 4 / 4 |
| CER against the input transcript | 0.000 – 0.030 | 0.000 – 0.027 | 4 / 4 |

36 of 36 measures are within the reference's own spread. For the per-output measures (MOS and
CER against the input) the columns compare the outputs of each implementation rather than pairs.
The MFCC distortion uses librosa MFCCs, so its values are not comparable with published
mel-cepstral distortion figures; only the comparison between the columns is meaningful.
With four seeds, the 40 kHz voicing agreement that looked low in the single-seed
conformance test (95.6 % against 99.1 %) is within the reference spread (0.947 – 0.965
against 0.948 – 0.955).

### Speed and memory (same machine, CPU)

| Input | Time | Peak memory |
|---|---|---|
| 3.4 s, v2 40 kHz | 1.2 s (RTF 0.35) plus 0.8 s to load | 1.7 – 2.0 GiB |
| 3.4 s, v2 48 kHz with index | 1.3 s (RTF 0.39) plus 1.0 s to load | 2.1 GiB |
| 60 s in one piece, v2 40 kHz | 9.0 s (RTF 0.15) | 6.0 GiB |

Memory grows with the square of the piece length (self-attention at 100 frames per
second). `Chunking` defaults to the reference's values for a capable GPU (3 / 10 / 60 /
65 s); smaller `center` and `max` bound the memory.

## Decisions on the specification's open questions (section 15)

1. **Reading `.pth`**: read directly, no import step. The reader is about 600 lines, runs
   no code from the file, and the synthesizer graph is built from the weights in under a
   second, so a converted format would add a cache to keep in sync and nothing else.
2. **Graphs**: three separate graphs. HuBERT and RMVPE are fixed and shipped as ONNX
   files; the synthesizer differs per voice model and is generated at load time. FAISS is
   replaced by an own reader and search: the tested index (88 024 × 768) scans one list
   of about 40 vectors per frame, which needs no library.
3. **Precision**: fp32 everywhere for now; half-precision model files are widened on
   load. The tolerances above are for fp32. fp16 execution is left for the GPU work.
4. **v1**: supported in the code (features, synthesizer, model reader) and verified with
   random weights; verification with a real v1 model is open.
5. **CPU**: offline conversion runs several times faster than real time on the test
   machine. Whether CPU streaming is viable needs Phase 2 measurements on weaker CPUs.
6. **Formant shift**: not included.

Where the specification leaves a detail open, the behaviour was taken from black-box
comparison with the reference and is asserted by the conformance tests:

- The distance `d` in the blend weight `(1 / d)^2` is the value the index reports, which
  for these L2 indexes is the *squared* distance.
- The search is the index's own approximate search (the closest `nprobe` lists, `nprobe`
  read from the file), not an exhaustive one.
- Leading and trailing unvoiced frames take the nearest voiced F0.
- Quantised pitch rounds half to even.
- The excitation's phase rule (per-frame linear phase, carried across frames) and noise
  levels, which section 9.1 only names.
- The loudness mix uses the high-passed input.

Two things are deliberately left as they are: an exact index hit (`d = 0`) gives a
non-finite weight, as the formula says, and the input level is used as given. The
conformance runs enter the reference at its pipeline, as the specification describes it;
whether a caller should normalise the peak first is a question for the specification.

## Reimplementation discipline (spec section 14)

No reference source was copied or adapted. The network layout comes from the published
architectures (VITS, HiFi-GAN, NSF, HuBERT) and from the names and shapes of the tensors
in the model files; behaviour the specification does not pin down was determined by
running the reference and comparing numbers. The Python scripts under `reference/` only
call the reference through its entry points (found from their signatures); they are test
tooling and are not shipped.
