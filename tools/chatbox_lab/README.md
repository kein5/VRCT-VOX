# Chatbox lab

Tools for collecting VRChat chatbox screenshots to train VRCT-VOX's own chatbox detector. The upstream VRCT detector may not be shipped with VRCT-VOX, and its outputs may not be used for training, so the data comes only from this lab.

Capture only in the lab's own local test instance, or in an invite-only instance of the lab's private world joined by the lab's own accounts. Never capture other people, and do not publish the collected images, since avatars that appear in them belong to their creators.

## Parts

| Path | What it does |
|---|---|
| `unity/Runtime/ChatboxLabDirector.cs` | UdonSharp. Every few seconds it moves the speaker (the first client, instance master) to a zone, and the camera client to a random distance and angle in front of it. |
| `unity/Editor/ChatboxLabSceneBuilder.cs` | Builds `Assets/ChatboxLab/ChatboxLab.unity`. Eight plain zones with different backgrounds and light, plus signs with text as hard negatives. Each zone has post-processing set from the reference camera. It uses no third-party assets apart from three OFL fonts. |
| `unity/Editor/ChatboxLabThemes.cs` | Ten more zones that look like common VRChat worlds: a Japanese room, a night rooftop, a club, a cafe, a mirror lounge, a park, a beach, a sci-fi lobby, a classroom and an avatar gallery. They have ceilings and lamps, sky domes, glowing signs, video screens, mirrors, and dark world-info panels with white text, which look most like a chatbox. |
| `unity/Editor/ChatboxLabPreview.cs` | Renders each zone to `~/.cache/vrct-vox-chatbox-lab/previews/` for review. |
| `unity/Editor/ChatboxLabBuild.cs` | Builds the world bundle with the SDK and copies it to `~/.cache/vrct-vox-chatbox-lab/world.vrcw`, or uploads it as a private world and keeps its id in `world-id`. The SDK needs you to be signed in. |
| `unity/Editor/ChatboxLabRemote.cs`, `unity_remote.py` | Run the lab's menu actions (build the scene, render previews, build, upload) in an editor that is already open, since batch mode cannot open the same project. |
| `launch_clients.py` | Starts the test clients through Proton, as the SDK's Build & Test does on Windows. Each client gets its own profile and OSC ports, and all join a hidden local instance, or with `--online` an invite-only instance of the uploaded world. |
| `collect.py` | Sends chat text to the speaker over OSC (`/chatbox/input`) and captures the camera client's window. Frames are saved with the text on screen, including negatives with no chatbox. |
| `label.py` | Labels frames automatically. It keeps only the PP-OCR lines that belong to the sent message, so the nameplate and signs stay out, and pads their bounds into a chatbox box. Unsure frames and negatives with a fading message are left out. |
| `yolox/` | Trains YOLOX-Tiny from Megvii's COCO weights (Apache-2.0), exports ONNX in the layout `BubbleDetector` reads, and holds the dataset split and settings. Adapted from upstream VRCT's training tools (MIT). |

## Setup

1. Create a Unity 2022.3.22f1 project with `com.vrchat.worlds` (here `~/ALCOM/projects/vrct-vox-chatbox-lab`). Copy `unity/Runtime/*.cs` to `Assets/ChatboxLab/` and `unity/Editor/*.cs` to `Assets/ChatboxLab/Editor/`. For Japanese text, copy M PLUS 1p, Zen Kaku Gothic New and BIZ UDPGothic (`*-Regular.ttf`, SIL Open Font License, from Google Fonts) to `Assets/ChatboxLab/Fonts/`.
2. Run **VRCT-VOX > Build Chatbox Lab Scene** twice: the first run creates the U# program asset, the second builds the scene. Batch mode also works:
   `Unity -batchmode -projectPath <project> -executeMethod ChatboxLabSceneBuilder.BuildScene -quit`.
3. Sign in under **VRChat SDK > Show Control Panel**, then run **VRCT-VOX > Build Chatbox Lab World**.
4. Run `python tools/chatbox_lab/launch_clients.py --clients 2`. It uses the VRChat account already signed in on this PC.
5. Once both clients are in the world, run `python tools/chatbox_lab/collect.py --minutes 30`.

In the local test instance only the account's own avatars load; on VRChat's servers, avatars by other creators are expected to load too. Create the private world once with **Build and Upload** in the SDK panel, then run `python tools/chatbox_lab/unity_remote.py save-world-id`; later uploads can use `unity_remote.py upload`. Sign the camera profile in to the lab's second account, start the clients with `launch_clients.py --online`, and invite the camera account from the speaker if VRChat does not let it in by the link.
6. Close the clients with `python tools/chatbox_lab/launch_clients.py --stop`.
7. Label each session: `python tools/chatbox_lab/label.py ~/.cache/vrct-vox-chatbox-lab/dataset/raw/<session>`. Check `review.png`.

## Training

The training environment lives in `~/.cache/vrct-vox-chatbox-lab/train`:

- `yolox-src`: YOLOX at commit `6ddff4824372906469a7fae2dc3206c7aa4bbaee` (main, 2025-06-08). Tag 0.3.0 predates the `get_dataset` API.
- `yolox_tiny.pth`: from the YOLOX `0.1.1rc0` release, SHA-256 `9de513de589ac98bb92d3bca53b5af7b9acfa9b0bacb831f7999d0f7afaee8f0`.
- `venv`: Python 3.11 with PyTorch 2.7 (CUDA 12.6), torchvision, pycocotools, onnx, onnxruntime, loguru, thop, tabulate, scikit-image.

```sh
T=~/.cache/vrct-vox-chatbox-lab/train
$T/venv/bin/python tools/chatbox_lab/yolox/prepare.py
PYTHONPATH=$T/yolox-src $T/venv/bin/python tools/chatbox_lab/yolox/train.py -b 8
PYTHONPATH=$T/yolox-src $T/venv/bin/python tools/chatbox_lab/yolox/export.py
```
