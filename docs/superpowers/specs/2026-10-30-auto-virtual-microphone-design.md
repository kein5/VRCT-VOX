# Automatic Linux virtual microphone

The user wants VRCT to create its virtual microphone instead of requiring terminal commands. Existing permission to implement autonomously applies; no new agents, commits, or publication. Implementation choices below are the implementer's decisions.

## Approach

Use three persistent systemd user services running the system `pw-loopback`. Start/enable them when the managed audio route is first selected, or a saved managed route is opened. Reuse a complete existing v1 route without installing anything. Never restart PipeWire, WirePlumber, SteamVR, or other applications. No root access, downloads, or microphone capture is involved in provisioning.

Alternatives: installing the existing PipeWire fragment requires a disruptive daemon restart; app-owned loopbacks disappear on app exit and can cause consumer microphone fallback. User services keep endpoints independent of the GUI and inference worker, with initial source mute. Services use host executables, never a temporary AppImage mount. They are recreated muted at login. App exit and switching away from managed mode mute the route without removing it.

## Contract

- Only Linux with systemd user manager and PipeWire tools is automatically provisioned. Existing manual routes continue to work without systemd.
- Preserve node names/markers, shared source mute, direct branch gate, and endpoint identity checks. Preparation is asynchronous in the existing route worker; a command's success is not endpoint readiness.
- Serialize setup across app instances. Reuse only recognized services; refuse foreign files, masks, drop-ins and conflicting graph objects. Never replace or delete someone else's nodes/files. Partial owned setup may be retried.
- Missing tools, unavailable manager, filesystem errors, timeouts and graph conflicts remain visible errors with software output closed. No automatic unmute. No physical input is selected or recorded.
- Move Audio route to the top of Device settings, describe automatic setup and explain that physical RVC input is selected on the RVC page. Existing legacy microphone enumeration remains outside scope.
- Native verification uses isolated PipeWire for PCM/gate/lifetime checks; host installation, if tested, preserves unrelated services/default devices and avoids touching user recording streams.

## Evidence

PipeWire loopback documentation: https://docs.pipewire.org/page_module_loopback.html
systemd service and unit documentation: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html and https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
Existing ADR-005 and `config/pipewire/90-vrct-managed.conf` define the compatibility boundary.

## Limits

Service/daemon failure can still remove endpoints; automatic setup does not prove zero fallback in consumer applications. SIGKILL does not run normal final mute. Native Wayland input and legacy ASR portability are separate work.
