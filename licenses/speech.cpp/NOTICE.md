# speech.cpp binary component

This component contains the unmodified `speech` executable extracted from an
official speech.cpp 0.9.0 Linux release. `bundle.json` records the selected
archive, its SHA256, the source commit and the hashes of the files included here.
No speech model, reference recording, libspeech shared library or VC engine is
included. This is a VRCT-VOX packaging component, not an upstream release of VRCT.

Upstream source: https://github.com/nyosegawa/speech.cpp
Commit: 49f022a48bc1c7e797aa64dd08d2d9655baf299e
Release: https://github.com/nyosegawa/speech.cpp/releases/tag/v0.9.0

The executable includes the following code; preserve the accompanying notices:

- speech.cpp: MIT, Copyright (c) 2026 Sakasegawa; `speech.cpp-LICENSE`.
- GGML: MIT; `ggml-LICENSE`. Submodule commit
  cbdeccfd49ec9c702c175c273d36c47520cf4710.
- cpp-httplib: MIT; `cpp-httplib-LICENSE`. Vendored commit
  cf3693cb5cc0d39b0e6f4122ba89bda9edb5ac6b.
- miniaudio: public domain or MIT, as provided in `miniaudio-LICENSE`.
  Vendored commit 9634bedb5b5a2ca38c1ee7108a9358a4e233f14d.
- Statically linked GCC runtime libraries: GNU GPL version 3 with the GCC Runtime
  Library Exception version 3.1. Both `GCC-COPYING3` and `GCC-COPYING.RUNTIME`
  are included. The inspected official Linux Vulkan binary identifies GCC
  Ubuntu 11.4.0-1ubuntu1~22.04.3. The license documents are from the GCC 11.4.0
  release: https://github.com/gcc-mirror/gcc/tree/releases/gcc-11.4.0 .

The upstream build links GGML, libstdc++ and libgcc statically; this does not make
every part of the resulting executable exclusively MIT-licensed. The runtime
exception covers eligible compilation as specified in its exact text.

The Linux executable requires a compatible operating system (upstream states
glibc 2.34 or newer). The Vulkan variant also requires an installed Vulkan loader
and driver. Those OS libraries and drivers are not redistributed in this
component. Models and separately installed VC runtimes have their own conditions.
