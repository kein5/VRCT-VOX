import React from 'react'
import { Bubble, Caption, FIGURE_Y, Field, Figure, LaneLabel, Stage, Step, Wire, arrive, draw, leave, light, typeIn, useTimeline } from '../parts'
import { Lang, copy, say } from '../copy'

// You type in your language; the translation lands in the chatbox above your avatar.
export const Translate: React.FC<{ lang: Lang }> = ({ lang }) => {
  const t = copy.translate
  const scope = useTimeline((tl, q) => {
    arrive(tl, '#field', 0.3)
    const typed = typeIn(tl, q, '#typed', 0.7)
    draw(tl, 'w1', typed + 0.3)
    arrive(tl, '#step', typed + 0.55)
    light(tl, 'step', 'mine', typed + 0.7)
    draw(tl, 'w2', typed + 1.0)
    arrive(tl, '#you, #you-label', typed + 1.25)
    arrive(tl, '#bubble', typed + 1.5)
    leave(tl)
  })
  return (
    <Stage ref={scope}>
      <LaneLabel side="mine" text={say(copy.laneMine, lang)} />
      <Field id="field" x={72} y={420} w={400} label={say(t.box, lang)}>
        <span id="typed">{say(t.input, lang)}</span>
      </Field>
      <Wire id="w1" x1={480} x2={556} y={420} side="mine" />
      <Step id="step" x={556} y={420} w={220} label={say(t.node, lang)} />
      <Wire id="w2" x1={784} x2={900} y={420} side="mine" />
      <Figure id="you" x={1060} y={FIGURE_Y} side="mine" />
      <Bubble id="bubble" x={1060} y={FIGURE_Y - 210} text={say(t.output, lang)} />
      <Caption id="you-label" x={940} y={FIGURE_Y + 76} w={240} text={say(t.place, lang)} />
    </Stage>
  )
}
