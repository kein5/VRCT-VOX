"""Draws the "how voice and text flow" diagram of the user guide, in Japanese and English.

    python tools/draw_flow_diagram.py

writes site/public/diagrams/how-it-works-{ja,en}.svg. The two lanes read left to right: what
you say or type, on its way to the other players (blue, like your own lines in the app), and
what they say or write, on its way to you (purple, like theirs). Run it again after changing a
name here; the names follow the app's (locales/*.yml).
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "site" / "public" / "diagrams"
WIDTH, HEIGHT = 980, 560
BOX_H = 46
COLORS = dict(back="#111b2c", box="#18233a", line="#3b4a66", text="#e6edf7", note="#a9b6cc",
              mine="#6ea8ff", theirs="#b48cff")
# id: (x, y, width, lane)
BOXES = {
    "chat": (20, 78, 180, "mine"), "mic": (20, 168, 180, "mine"),
    "asr1": (235, 168, 190, "mine"), "tr1": (455, 123, 120, "mine"),
    "tts": (610, 168, 190, "mine"), "rvc": (610, 248, 190, "mine"),
    "chatbox": (830, 78, 140, "mine"), "vmic": (830, 208, 140, "mine"),
    "voice": (20, 388, 180, "theirs"), "screen": (20, 478, 180, "theirs"),
    "asr2": (235, 388, 190, "theirs"), "ocr": (235, 478, 190, "theirs"),
    "tr2": (455, 433, 120, "theirs"),
    "log": (830, 388, 140, "theirs"), "obs": (830, 478, 140, "theirs"),
}
# (from, to, dashed)
EDGES = [("mic", "asr1", False), ("asr1", "tr1", False), ("chat", "tr1", False), ("tr1", "chatbox", False),
         ("tr1", "tts", False), ("tts", "vmic", False), ("mic", "rvc", False), ("rvc", "vmic", False),
         ("tts", "rvc", True),
         ("voice", "asr2", False), ("asr2", "tr2", False), ("screen", "ocr", False), ("ocr", "tr2", False),
         ("tr2", "log", False), ("tr2", "obs", False)]
TEXT = {
    "ja": dict(
        title="声と文字の流れ", mine="自分の声と文字 → 相手へ", theirs="相手の声と文字 → 自分へ",
        mic="自分の声（マイク）", chat="チャット入力", asr1="音声認識（ASR）", tr1="翻訳",
        tts="テキスト読み上げ（TTS）", rvc="ボイスチェンジャー（RVC）", chatbox="VRChatの|チャットボックス",
        vmic="仮想マイク|→ VRChatのマイク", voice="相手の声（ゲーム音声）", screen="相手のチャットボックス",
        asr2="音声認識（ASR）", ocr="チャット読み取り（OCR）", tr2="翻訳", log="字幕とログ|（画面・VR）",
        obs="OBS・WebSocket", dashed="点線: 読み上げを声の変換に通すとき",
        note="自分の発言も、ログ、字幕、OBS・WebSocket に出ます。"),
    "en": dict(
        title="How voice and text flow", mine="Your voice and text → to them", theirs="Their voice and text → to you",
        mic="Your voice (mic)", chat="Typed chat", asr1="Speech recognition (ASR)", tr1="Translation",
        tts="Text to speech (TTS)", rvc="Voice changer (RVC)", chatbox="VRChat|chatbox",
        vmic="Virtual mic|→ VRChat's mic", voice="Their voice (game)", screen="Their chatbox",
        asr2="Speech recognition (ASR)", ocr="Chat reading (OCR)", tr2="Translation", log="Captions and log|(screen, VR)",
        obs="OBS, WebSocket", dashed="Dotted: speech through the voice changer",
        note="Your own words also go to the log, captions, OBS and WebSocket."),
}


def box_text(x, y, w, label):
    lines = label.split("|")
    top = y + BOX_H / 2 - (len(lines) - 1) * 8
    return "".join(
        f'<text x="{x + w / 2:.0f}" y="{top + i * 16:.0f}" text-anchor="middle" dominant-baseline="middle">{escape(line)}</text>'
        for i, line in enumerate(lines))


def edge(start, end, dashed):
    x1, y1, w1, lane = BOXES[start]
    x2, y2, w2, _ = BOXES[end]
    if start == "tts" and end == "rvc":  # stacked boxes: straight down
        cx = x1 + w1 / 2
        path = f"M{cx:.0f},{y1 + BOX_H} L{cx:.0f},{y2 - 4}"
    elif start == "mic" and end == "rvc":  # the live voice leaves the mic from below, under the text steps
        sx, sy, ex, ey = x1 + w1 / 2, y1 + BOX_H, x2 - 4, y2 + BOX_H / 2
        path = f"M{sx:.0f},{sy} C{sx:.0f},{ey} {ex - 120:.0f},{ey:.0f} {ex:.0f},{ey:.0f}"
    else:
        sx, sy, ex, ey = x1 + w1, y1 + BOX_H / 2, x2 - 4, y2 + BOX_H / 2
        bend = max(20, (ex - sx) / 2)
        path = f"M{sx:.0f},{sy:.0f} C{sx + bend:.0f},{sy:.0f} {ex - bend:.0f},{ey:.0f} {ex:.0f},{ey:.0f}"
    dash = ' stroke-dasharray="5 5"' if dashed else ""
    return f'<path d="{path}" fill="none" stroke="{COLORS[lane]}" stroke-width="2"{dash} marker-end="url(#arrow-{lane})"/>'


def draw(language):
    t = TEXT[language]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
             f'role="img" aria-labelledby="title" font-family="system-ui, -apple-system, \'Segoe UI\', \'Hiragino Sans\', \'Noto Sans JP\', sans-serif" font-size="14">',
             f'<title id="title">{escape(t["title"])}</title>',
             '<defs>' + "".join(
                 f'<marker id="arrow-{lane}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">'
                 f'<path d="M0,0 L8,4 L0,8 z" fill="{COLORS[lane]}"/></marker>' for lane in ("mine", "theirs")) + '</defs>',
             f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="{COLORS["back"]}"/>',
             f'<text x="20" y="42" fill="{COLORS["mine"]}" font-weight="600" font-size="15">{escape(t["mine"])}</text>',
             f'<text x="20" y="352" fill="{COLORS["theirs"]}" font-weight="600" font-size="15">{escape(t["theirs"])}</text>',
             f'<line x1="20" y1="322" x2="{WIDTH - 20}" y2="322" stroke="{COLORS["line"]}" stroke-width="1"/>']
    parts += [edge(*row) for row in EDGES]
    for name, (x, y, w, lane) in BOXES.items():
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{BOX_H}" rx="8" fill="{COLORS["box"]}" stroke="{COLORS[lane]}" stroke-width="1.5"/>')
        parts.append(f'<g fill="{COLORS["text"]}">{box_text(x, y, w, t[name])}</g>')
    parts.append(f'<text x="610" y="316" fill="{COLORS["note"]}" font-size="12">{escape(t["dashed"])}</text>')
    parts.append(f'<text x="{WIDTH - 20}" y="{HEIGHT - 14}" text-anchor="end" fill="{COLORS["note"]}" font-size="12">{escape(t["note"])}</text>')
    parts.append("</svg>\n")
    return "".join(parts)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for language in TEXT:
        (OUT / f"how-it-works-{language}.svg").write_text(draw(language), encoding="utf-8", newline="\n")
        print(OUT / f"how-it-works-{language}.svg")
