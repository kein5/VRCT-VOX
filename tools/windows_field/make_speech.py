"""Write the English test sentences with Windows' own speech synthesis. No audio file is kept in the repository."""
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2])
OUT = ROOT / 'build/model-test/windows-field/wavs'
SENTENCES = {'en-1': 'Hello everyone. The weather is very nice today.',
             'en-2': 'Thank you for coming to the meeting this morning.'}
SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono')
$voice.SetOutputToWaveFile($env:VOX_WAV, $format)
$voice.Speak($env:VOX_TEXT)
$voice.Dispose()
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in SENTENCES.items():
        path = OUT / f'{name}.wav'
        subprocess.run(['powershell', '-NoProfile', '-Command', SCRIPT], check=True, env=dict(os.environ, VOX_WAV=str(path), VOX_TEXT=text))
        print(path, path.stat().st_size, flush=True)


if __name__ == '__main__':
    main()
