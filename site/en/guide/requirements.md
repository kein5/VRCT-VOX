# System requirements

What your PC needs depends on the features you use. Text translation and captions of other people's voices need no GPU. Speech, the voice changer and VRChat on the same PC at once need more memory and a capable GPU.

The values on this page were measured on one test PC or worked out from model sizes. They are estimates, not guarantees. The test PC is listed at the end of the page.

## Operating systems

| OS | Requirements |
|---|---|
| Windows | Tested on 64-bit Windows 11. Not tested on Windows 10. Needs the WebView2 Runtime; the installer fetches it if it is missing. |
| Linux | An x86-64 PC with glibc 2.39 or later, GTK 3 and WebKitGTK 4.1. The deb and rpm are tested to install on Ubuntu 24.04, Debian 13 and Fedora 44. Real models are tested on CachyOS (KDE Plasma, Wayland). |

There is no macOS version.

On Linux, the audio route the app manages needs Linux 6.9 or later, PipeWire and WirePlumber 0.5 ([Linux audio](linux-audio)). The desktop caption overlay runs under X11 or XWayland.

## Memory

| Use | Memory the app used (measured) | Suggested PC memory |
|---|---|---|
| Translation and captions of other people's voices (Whisper tiny for recognition, both on the CPU) | about 3.6 GB | 16 GB or more |
| Speech, captions, the voice changer (RVC), translation and VR captions at once | about 11.5–13.1 GB | 32 GB or more |

"Memory the app used" is the total private memory of the VRCT-VOX processes, measured over runs of 30 minutes to 2 hours. "Suggested PC memory" adds the operating system and VRChat to that. VRChat's own memory was not measured.

## GPU

| Feature | GPU needed |
|---|---|
| Translation, speech recognition (Whisper), chat reading | None; they run on the CPU |
| Speech, realtime captions and telling speakers apart (speech.cpp, included in the app) | A GPU with Vulkan support: NVIDIA, AMD or Intel, integrated GPUs included. Without one they run on the CPU, more slowly |
| Voice changer (RVC, Seed-VC) | An NVIDIA GPU with a driver that supports CUDA 12.8 |
| Whisper and local translation on the GPU (the Windows CUDA version) | An NVIDIA GPU |

The speech models use about this much GPU memory (more in [Getting models](models#gpu-and-memory-guidance)):

| Model | GPU memory |
|---|---|
| Irodori-TTS v4.1 Small MF · F16 (Japanese) | about 2.3 GB |
| Irodori-TTS v4.1 Small MF · Q8_0 (Japanese, compact) | about 1.6 GB |
| Qwen3-TTS 0.6B · Q8_0 (other languages) | about 1.3 GB |
| Qwen3-TTS 0.6B · Q5_K (other languages, compact) | about 1.0 GB |

On a GeForce RTX 3060 Ti (8 GB), speech, captions and RVC together used about 4.8 GB of GPU memory. With VRChat (desktop mode) on the same GPU it was about 6.1 GB, with a peak of about 7.2 GB. To run every feature with VRChat on one GPU, plan for 8 GB of GPU memory or more. VRChat on a VR headset was not measured.

## CPU

The only CPU tested is an Intel Core i7-1255U (a laptop CPU with 10 cores and 12 threads). There is no set minimum CPU.

| Use | CPU use (100% = one logical core) |
|---|---|
| Translation and captions of other people's voices (both on the CPU) | 21–34% |
| Speech, captions and RVC on the GPU, translation on the CPU | 63–137% |

## Free disk space

| Item | Size |
|---|---|
| App (Windows, CPU version) | ZIP about 0.4 GB, about 1.1 GB unpacked |
| App (Windows, CUDA version) | ZIP about 1.7 GB, about 3.0 GB unpacked |
| App (Linux) | about 0.5 GB to download, about 1.3 GB unpacked |
| Translation model (one) | 0.4–3.3 GB |
| Speech models (one for Japanese, one for other languages) | 0.8–1.8 GiB each |
| Speech recognition model | 0.6–0.8 GiB |
| RVC runtime | needs about 12 GB free on Windows, 16 GB on Linux |
| Seed-VC runtime | needs about 14 GB free on Windows, 18 GB on Linux |

For every feature on Windows, plan for about 20 GB free with RVC, or about 35 GB with Seed-VC as well. The models and their sizes are listed in [Getting models](models).

## Test PC

| Part | Configuration |
|---|---|
| OS | Windows 11 |
| CPU | Intel Core i7-1255U |
| Memory | 32 GB |
| GPU | NVIDIA GeForce RTX 3060 Ti (8 GB, connected over Thunderbolt), Intel Iris Xe (integrated) |

The measurements are recorded in the developer [Windows voice report](https://github.com/kein5/VRCT-VOX/blob/develop/docs/voice-stack/windows-voice-report.md).
