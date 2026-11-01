# Linux audio route

For VRChat to hear speech or converted voice, VRCT-VOX's audio has to reach VRChat's microphone input. On Linux, VRCT-VOX can create a virtual microphone (PipeWire) that it manages.

## Using the managed virtual microphone

1. Under Settings → "Device" → "Audio route", choose "Managed virtual microphone (Linux)" and save. Setup starts automatically. You can also start it with "Prepare and use virtual microphone" on the "RVC" page.
2. When it is ready, press "Resume voice". The virtual microphone is created muted.
3. In VRChat, choose "VRCT Managed Virtual Microphone" as your microphone.

No administrator rights are needed. You need PipeWire and systemd user services.

### What the app does

- Creates and enables three user services, `vrct-managed-source`, `vrct-managed-tts` and `vrct-managed-vc`, in `~/.config/systemd/user/`.
- Keeps the virtual microphone after VRCT-VOX exits. At your next login it is created again, muted.
- Reuses a working virtual microphone if one already exists.

### What the app does not do

- restart audio services such as PipeWire
- start recording your microphone or download models
- remove the virtual microphone when it exits, because an app using it could suddenly switch to another microphone

## Mute and resume

"Mute until resumed" under "Device" → "Audio route" stops both speech and voice conversion going through this virtual microphone. Press "Resume voice" to resume. When you start VRCT-VOX again, it starts muted.

## Removing the virtual microphone

1. Quit VRCT-VOX.
2. Switch VRChat and any other app using the virtual microphone to another microphone.
3. Stop and disable only the three user services above.

```sh
systemctl --user disable --now vrct-managed-source.service vrct-managed-tts.service vrct-managed-vc.service
```

## Using an existing external cable

If you already have a virtual cable, set "Audio route" to "Existing external cable" and choose the cable under "Output device" on the "TTS" page. In VRChat, choose the cable's recording end as your microphone. In this mode, "Mute until resumed" stops VRCT-VOX's speech only.
