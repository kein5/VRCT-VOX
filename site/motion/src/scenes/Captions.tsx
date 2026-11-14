import React from 'react'
import { Caption, FIGURE_Y, Figure, LaneLabel, Stage, Step, Waveform, Wire, arrive, draw, leave, light, speak, textIn, useTimeline } from '../parts'
import { C } from '../theme'
import { Lang, copy, say } from '../copy'

// Another player speaks; their words appear as a caption, with the translation under it.
export const Captions: React.FC<{ lang: Lang }> = ({ lang }) => {
  const t = copy.captions
  const scope = useTimeline((tl, q) => {
    arrive(tl, '#them, #them-label', 0.3)
    speak(tl, 'them', 0.6)
    draw(tl, 'w1', 1.2)
    arrive(tl, '#step', 1.45)
    light(tl, 'step', 'theirs', 1.6)
    draw(tl, 'w2', 1.9)
    arrive(tl, '#panel, #panel-label', 2.15)
    textIn(tl, q, '#heard', 2.35)
    arrive(tl, '#translated', 3.3)
    leave(tl)
  })
  return (
    <Stage ref={scope}>
      <LaneLabel side="theirs" text={say(copy.laneTheirs, lang)} />
      <Figure id="them" x={190} y={FIGURE_Y} side="theirs" />
      <Caption id="them-label" x={90} y={FIGURE_Y + 76} w={200} text={say(copy.vrchat, lang)} />
      <Waveform x={300} y={420} w={170} side="theirs" start={0.6} />
      <Wire id="w1" x1={490} x2={560} y={420} side="theirs" />
      <Step id="step" x={560} y={420} w={220} label={say(t.node, lang)} />
      <Wire id="w2" x1={788} x2={860} y={420} side="theirs" />
      {/* The panel and its label stack in one column, so a caption that wraps never covers the label. */}
      <div style={{ position: 'absolute', left: 860, top: 350, width: 390 }}>
        <div
          id="panel"
          className="part"
          style={{ boxSizing: 'border-box', padding: '20px 24px', borderRadius: 14, border: `2px solid ${C.hairline}`, background: C.rail }}
        >
          <div id="heard" style={{ fontSize: 30, fontWeight: 600, lineHeight: 1.3 }}>
            {say(t.heard, lang)}
          </div>
          <div id="translated" style={{ fontSize: 26, color: C.text2, marginTop: 8 }}>
            {say(t.translated, lang)}
          </div>
        </div>
        <div id="panel-label" className="part" style={{ marginTop: 14, textAlign: 'center', fontSize: 24, color: C.text3 }}>
          {say(t.place, lang)}
        </div>
      </div>
    </Stage>
  )
}
