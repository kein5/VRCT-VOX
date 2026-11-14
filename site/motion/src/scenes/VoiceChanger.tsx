import React from 'react'
import { Caption, FIGURE_Y, Figure, LaneLabel, Stage, Step, Waveform, Wire, arrive, draw, leave, light, speak, useTimeline } from '../parts'
import { C } from '../theme'
import { Lang, copy, say } from '../copy'

// Your voice goes in rough and comes out as another voice, while you keep talking.
export const VoiceChanger: React.FC<{ lang: Lang }> = ({ lang }) => {
  const t = copy.voice
  const scope = useTimeline((tl) => {
    arrive(tl, '#mic, #mic-label', 0.3)
    draw(tl, 'w1', 1.0)
    arrive(tl, '#step', 1.25)
    light(tl, 'step', 'mine', 1.4)
    draw(tl, 'w2', 2.1)
    arrive(tl, '#you, #you-label', 2.35)
    speak(tl, 'you', 2.55)
    leave(tl)
  })
  return (
    <Stage ref={scope}>
      <LaneLabel side="mine" text={say(copy.laneMine, lang)} />
      <svg id="mic" className="part" style={{ position: 'absolute', inset: 0 }} width={1280} height={800}>
        <rect x={86} y={360} width={48} height={84} rx={24} fill={C.raised} stroke={C.border} strokeWidth={2} />
        <path d="M70,410 C70,450 150,450 150,410 M110,446 L110,476 M88,476 L132,476" fill="none" stroke={C.border} strokeWidth={4} strokeLinecap="round" />
      </svg>
      <Caption id="mic-label" x={50} y={500} w={120} text={say(t.mic, lang)} />
      <Waveform x={190} y={420} w={180} side="mine" start={0.5} />
      <Wire id="w1" x1={390} x2={450} y={420} side="mine" />
      <Step id="step" x={450} y={420} w={320} label={say(t.node, lang)} />
      <Waveform x={800} y={420} w={150} side="mine" shape="smooth" start={1.7} />
      <Wire id="w2" x1={960} x2={1020} y={420} side="mine" />
      <Figure id="you" x={1120} y={FIGURE_Y} side="mine" />
      <Caption id="you-label" x={1040} y={FIGURE_Y + 76} w={160} text={say(copy.vrchat, lang)} />
    </Stage>
  )
}
