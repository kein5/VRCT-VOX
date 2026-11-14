Before publishing this draft (tools/changelog.py puts this list in a comment, which the release page does not show):
- Write the Highlights, Upgrade Notes and Known Issues below; the changes come from CHANGELOG.md.
- Check the candidate manifests, SHA256SUMS, Linux GUI acceptance and Windows install/upgrade/uninstall results.
- Confirm model/runtime licenses and supported platforms. No user voice models are bundled.
- TTS/RVC hardware results apply only to the recorded device and configuration. Windows hardware acceptance is separate from building the installer.
- The installer uses `VRCT-VOX.zip` / `VRCT-VOX_cuda.zip` from this release; keep these names and the stable `VRCT-VOX_setup.exe` asset.
- Application auto-update remains disabled. Configuration and cache retain the legacy storage identity.
