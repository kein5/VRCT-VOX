import React from 'react'
import { Bubble, Figure, LaneLabel, Stage, Step, Wire, arrive, draw, leave, light, textIn, useTimeline } from '../parts'
import { C } from '../theme'
import { Lang, copy, say } from '../copy'

// A chatbox on the VRChat screen is read and appears translated in your log.
export const ChatReading: React.FC<{ lang: Lang }> = ({ lang }) => {
  const t = copy.chat
  const scope = useTimeline((tl, q) => {
    arrive(tl, '#screen, #screen-label', 0.3)
    arrive(tl, '#them', 0.5)
    arrive(tl, '#bubble', 0.8)
    // The reading frame finds the chatbox and sweeps across it, then gets out of the way.
    tl.fromTo('#scan', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.2, ease: 'power2.out' }, 1.5)
    tl.fromTo('#scan .sweep', { attr: { x1: 80, x2: 80 } }, { attr: { x1: 480, x2: 480 }, duration: 0.8, ease: 'power1.inOut' }, 1.6)
    tl.to('#scan', { autoAlpha: 0, duration: 0.2, ease: 'power3.in' }, 2.5)
    draw(tl, 'w1', 2.5)
    arrive(tl, '#step', 2.75)
    light(tl, 'step', 'theirs', 2.9)
    draw(tl, 'w2', 3.2)
    arrive(tl, '#log, #log-label', 3.45)
    textIn(tl, q, '#translated', 3.65)
    leave(tl)
  })
  return (
    <Stage ref={scope}>
      <LaneLabel side="theirs" text={say(copy.laneTheirs, lang)} />
      <div id="screen-label" className="part" style={{ position: 'absolute', left: 60, top: 226, fontSize: 22, color: C.text3 }}>
        {say(t.screen, lang)}
      </div>
      <div
        id="screen"
        className="part"
        style={{ position: 'absolute', left: 60, top: 262, width: 440, height: 330, borderRadius: 14, border: `2px solid ${C.hairline}`, background: C.rail }}
      />
      <Figure id="them" x={280} y={540} side="theirs" scale={0.8} />
      <Bubble id="bubble" x={280} y={330} text={say(t.seen, lang)} size={24} />
      <svg id="scan" style={{ position: 'absolute', inset: 0 }} width={1280} height={800}>
        <rect x={80} y={318} width={400} height={82} rx={10} fill="none" stroke={C.theirs} strokeWidth={3} strokeDasharray="10 8" />
        <line className="sweep" x1={80} y1={318} x2={80} y2={400} stroke={C.theirs} strokeWidth={3} />
      </svg>
      <Wire id="w1" x1={510} x2={570} y={420} side="theirs" />
      <Step id="step" x={570} y={420} w={284} label={say(t.node, lang)} />
      <Wire id="w2" x1={862} x2={912} y={420} side="theirs" />
      <div style={{ position: 'absolute', left: 912, top: 340, width: 348 }}>
        <div id="log" className="part" style={{ boxSizing: 'border-box', padding: '18px 22px', borderRadius: 14, border: `2px solid ${C.hairline}`, background: C.surface }}>
          <div style={{ fontSize: 20, fontWeight: 600, color: C.theirs }}>{say(t.received, lang)}</div>
          <div style={{ fontSize: 20, color: C.text3, marginTop: 6 }}>{say(t.seen, lang)}</div>
          <div id="translated" style={{ fontSize: 28, fontWeight: 600, marginTop: 4, lineHeight: 1.3 }}>
            {say(t.translated, lang)}
          </div>
        </div>
        <div id="log-label" className="part" style={{ marginTop: 14, textAlign: 'center', fontSize: 24, color: C.text3 }}>
          {say(t.log, lang)}
        </div>
      </div>
    </Stage>
  )
}
