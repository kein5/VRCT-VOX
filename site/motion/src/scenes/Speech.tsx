import React from 'react'
import { Caption, FIGURE_Y, Field, Figure, LaneLabel, Stage, Step, Waveform, Wire, arrive, draw, leave, light, speak, useTimeline } from '../parts'
import { Lang, copy, say } from '../copy'

// A line you sent is spoken, and the voice goes through the virtual mic into VRChat.
export const Speech: React.FC<{ lang: Lang }> = ({ lang }) => {
  const t = copy.tts
  const scope = useTimeline((tl) => {
    arrive(tl, '#field', 0.3)
    draw(tl, 'w1', 0.9)
    arrive(tl, '#tts', 1.15)
    light(tl, 'tts', 'mine', 1.3)
    draw(tl, 'w2', 1.9)
    arrive(tl, '#mic', 2.15)
    light(tl, 'mic', 'mine', 2.3)
    draw(tl, 'w3', 2.6)
    arrive(tl, '#you, #you-label', 2.85)
    speak(tl, 'you', 3.05)
    leave(tl)
  })
  return (
    <Stage ref={scope}>
      <LaneLabel side="mine" text={say(copy.laneMine, lang)} />
      <Field id="field" x={50} y={420} w={220} label={say(t.box, lang)}>
        {say(t.input, lang)}
      </Field>
      <Wire id="w1" x1={278} x2={336} y={420} side="mine" />
      <Step id="tts" x={336} y={420} w={200} label={say(t.node, lang)} />
      <Waveform x={556} y={420} w={140} side="mine" shape="smooth" start={1.5} />
      <Wire id="w2" x1={704} x2={760} y={420} side="mine" />
      <Step id="mic" x={760} y={420} w={200} label={say(t.mic, lang)} />
      <Wire id="w3" x1={968} x2={1024} y={420} side="mine" />
      <Figure id="you" x={1112} y={FIGURE_Y} side="mine" />
      <Caption id="you-label" x={1032} y={FIGURE_Y + 76} w={160} text={say(copy.vrchat, lang)} />
    </Stage>
  )
}
