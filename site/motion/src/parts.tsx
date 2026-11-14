import React, { useLayoutEffect, useRef } from 'react'
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import gsap from 'gsap'
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'
import { SplitText } from 'gsap/SplitText'
import { C, FONT, Side, laneColor } from './theme'

gsap.registerPlugin(DrawSVGPlugin, SplitText)

/** Every scene lasts 8 s and ends empty, as it began, so the video loops without a cut. */
export const LOOP_SECONDS = 8
export const LEAVE_AT = 7.3
/** The finished picture, used as the poster and for readers who prefer less motion. */
export const POSTER_SECONDS = 6.5
/** Scenes are laid out on a 1280×800 grid and shown 150px up in a 1280×500 frame. */
export const SIZE = { width: 1280, height: 500 }

export type Timeline = gsap.core.Timeline
export type Query = (selector: string) => Element[]

/**
 * Choreography lives in one paused GSAP timeline per scene, built once; every frame seeks it
 * to frame / fps. The same frame then always shows the same picture, whatever order the
 * renderer asks for frames in (the approach HyperFrames uses).
 */
export const useTimeline = (build: (tl: Timeline, q: Query) => void) => {
  const scope = useRef<HTMLDivElement>(null)
  const timeline = useRef<Timeline | null>(null)
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  useLayoutEffect(() => {
    const context = gsap.context(() => {
      const tl = gsap.timeline({ paused: true })
      build(tl, gsap.utils.selector(scope))
      timeline.current = tl
    }, scope)
    return () => context.revert()
  }, [])
  useLayoutEffect(() => {
    timeline.current?.seek(frame / fps)
  }, [frame, fps])
  return scope
}

// ---------- Moves (eases by role: arrivals land on a long tail, exits accelerate) ----------

/** A part arrives: blurred and slightly low, then sharp and in place. */
export const arrive = (tl: Timeline, targets: string, at: number) =>
  tl.fromTo(
    targets,
    { autoAlpha: 0, filter: 'blur(8px)', y: 10 },
    { autoAlpha: 1, filter: 'blur(0px)', y: 0, duration: 0.5, ease: 'expo.out' },
    at,
  )

/** A wire draws itself from its source, a signal riding its tip; the arrowhead lands last. */
export const draw = (tl: Timeline, id: string, at: number, duration = 0.45) => {
  tl.fromTo(`#${id} .line`, { drawSVG: '0%' }, { drawSVG: '100%', duration, ease: 'power2.inOut' }, at)
  tl.fromTo(`#${id} .dot`, { autoAlpha: 0, x: 0 }, { autoAlpha: 1, duration: 0.05 }, at)
  tl.to(`#${id} .dot`, { x: (_: number, el: Element) => Number(el.getAttribute('data-distance')), duration, ease: 'power2.inOut' }, at)
  tl.to(`#${id} .dot`, { autoAlpha: 0, duration: 0.12 }, at + duration - 0.04)
  tl.fromTo(`#${id} .head`, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.15 }, at + duration - 0.1)
}

/** A step lights in its lane's colour when the signal reaches it. */
export const light = (tl: Timeline, id: string, side: Side, at: number) =>
  tl.to(
    `#${id}`,
    { borderColor: laneColor(side), backgroundColor: side === 'mine' ? '#1d3157' : '#2a2650', color: C.text, duration: 0.3, ease: 'power2.out' },
    at,
  )

const japanese = (text: string) => /[぀-ヿ㐀-鿿]/.test(text)

/** Typing: characters appear one after another, as in an input field. */
export const typeIn = (tl: Timeline, q: Query, selector: string, at: number, perChar = 0.07) => {
  const split = SplitText.create(q(selector), { type: 'chars' })
  tl.fromTo(split.chars, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.01, stagger: perChar, ease: 'none' }, at)
  return at + split.chars.length * perChar
}

/** A line that is heard or read: words (characters in Japanese) sharpen in one after another. */
export const textIn = (tl: Timeline, q: Query, selector: string, at: number) => {
  const target = q(selector)
  const text = target[0]?.textContent ?? ''
  const jp = japanese(text)
  const split = SplitText.create(target, { type: jp ? 'chars' : 'words' })
  const items = jp ? split.chars : split.words
  tl.fromTo(items, { autoAlpha: 0, filter: 'blur(6px)' }, { autoAlpha: 1, filter: 'blur(0px)', duration: 0.14, stagger: jp ? 0.045 : 0.08, ease: 'power2.out' }, at)
}

/** Everything leaves together at the end of the loop, faster than it came. */
export const leave = (tl: Timeline, at = LEAVE_AT) =>
  tl.to('.part', { autoAlpha: 0, filter: 'blur(8px)', duration: 0.25, ease: 'power3.in', stagger: 0.025 }, at)

// ---------- Markup ----------

export const Stage = React.forwardRef<HTMLDivElement, { children: React.ReactNode }>(({ children }, ref) => (
  <AbsoluteFill style={{ background: C.bg, fontFamily: FONT, color: C.text }}>
    <div ref={ref} style={{ position: 'absolute', inset: 0, transform: 'translateY(-150px)' }}>
      {children}
    </div>
  </AbsoluteFill>
))

export const LaneLabel: React.FC<{ side: Side; text: string }> = ({ side, text }) => (
  <div style={{ position: 'absolute', left: 60, top: 176, fontSize: 26, fontWeight: 600, color: laneColor(side) }}>{text}</div>
)

/** A step of the route; `light()` colours it while it works. */
export const Step: React.FC<{ id: string; x: number; y: number; w: number; label: string }> = ({ id, x, y, w, label }) => (
  <div
    id={id}
    className="part"
    style={{
      position: 'absolute',
      left: x,
      top: y - 40,
      width: w,
      height: 80,
      boxSizing: 'border-box',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 14,
      border: `2px solid ${C.border}`,
      background: C.surface,
      color: C.text2,
      fontSize: 30,
      fontWeight: 600,
      textAlign: 'center',
      lineHeight: 1.25,
      padding: '0 12px',
    }}
  >
    {label}
  </div>
)

/** A wire from x1 to x2 at height y; `draw()` animates it. */
export const Wire: React.FC<{ id: string; x1: number; x2: number; y: number; side: Side }> = ({ id, x1, x2, y, side }) => {
  const lane = laneColor(side)
  return (
    <svg id={id} className="part" style={{ position: 'absolute', inset: 0, overflow: 'visible' }} width={1280} height={800}>
      <line className="line" x1={x1} y1={y} x2={x2 - 10} y2={y} stroke={lane} strokeOpacity={0.6} strokeWidth={3} strokeLinecap="round" />
      <path className="head" d={`M${x2 - 14},${y - 8} L${x2},${y} L${x2 - 14},${y + 8} z`} fill={lane} />
      <circle className="dot" cx={x1} cy={y} r={8} fill={lane} data-distance={x2 - 12 - x1} />
    </svg>
  )
}

/** A short label under a part of the scene. */
export const Caption: React.FC<{ id: string; x: number; y: number; w: number; text: string }> = ({ id, x, y, w, text }) => (
  <div id={id} className="part" style={{ position: 'absolute', left: x, top: y, width: w, textAlign: 'center', fontSize: 24, color: C.text3 }}>
    {text}
  </div>
)

const seconds = (frame: number, fps: number, from: number, to: number) =>
  interpolate(frame / fps, [from, to], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.16, 1, 0.3, 1) })

/**
 * Bars of a voice while it sounds, from `start` to `end` seconds. 'rough' is a speaking voice,
 * 'smooth' a changed or synthetic one. The bars move with the frame: a voice is live.
 */
export const Waveform: React.FC<{ x: number; y: number; w: number; side: Side; start: number; end?: number; shape?: 'rough' | 'smooth' }> = ({
  x,
  y,
  w,
  side,
  start,
  end = LEAVE_AT,
  shape = 'rough',
}) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const amp = Math.min(seconds(frame, fps, start, start + 0.35), 1 - seconds(frame, fps, end, end + 0.25))
  const bars = 22
  const gap = w / bars
  return (
    <svg style={{ position: 'absolute', inset: 0 }} width={1280} height={800} opacity={amp}>
      {Array.from({ length: bars }, (_, i) => {
        const wave =
          shape === 'rough'
            ? Math.abs(Math.sin(i * 1.7 + frame * 0.37) * Math.sin(i * 0.63 + frame * 0.13))
            : 0.55 + 0.45 * Math.sin(i * 0.55 - frame * 0.28)
        const h = 8 + 88 * amp * wave
        return <rect key={i} x={x + i * gap} y={y - h / 2} width={gap * 0.55} height={h} rx={gap * 0.27} fill={laneColor(side)} />
      })}
    </svg>
  )
}

/** A figure drawn at this y is centred on the route's line (y 420), level with the steps. */
export const FIGURE_Y = 440

/** A plain figure standing for a player; its sound arcs (`.arc`) show it speaking. */
export const Figure: React.FC<{ id: string; x: number; y: number; side: Side; scale?: number }> = ({ id, x, y, side, scale = 1 }) => (
  <svg id={id} className="part" style={{ position: 'absolute', inset: 0, overflow: 'visible' }} width={1280} height={800}>
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
      <circle cx={0} cy={-62} r={40} fill={C.raised} stroke={C.border} strokeWidth={2} />
      <path d="M-74,64 C-74,6 -40,-12 0,-12 C40,-12 74,6 74,64 Z" fill={C.raised} stroke={C.border} strokeWidth={2} />
      {[0, 1, 2].map((i) => (
        <path
          key={i}
          className="arc"
          d={`M${52 + i * 16},${-86 - i * 6} Q${66 + i * 22},${-62} ${52 + i * 16},${-38 + i * 6}`}
          fill="none"
          stroke={laneColor(side)}
          strokeWidth={4}
          strokeLinecap="round"
          opacity={0}
        />
      ))}
    </g>
  </svg>
)

/** The figure's sound arcs come on, nearest first. */
export const speak = (tl: Timeline, id: string, at: number) =>
  tl.fromTo(`#${id} .arc`, { opacity: 0 }, { opacity: (i: number) => 0.9 - i * 0.25, duration: 0.2, stagger: 0.08, ease: 'power2.out' }, at)

/** A chatbox bubble as players see it in the world. */
export const Bubble: React.FC<{ id: string; x: number; y: number; text: string; size?: number }> = ({ id, x, y, text, size = 32 }) => (
  <div id={id} className="part" style={{ position: 'absolute', left: x, top: y, translate: '-50% 0' }}>
    <div style={{ position: 'relative', padding: '14px 24px', borderRadius: 16, background: C.bubble, color: C.bubbleText, fontSize: size, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {text}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          bottom: -12,
          marginLeft: -12,
          borderLeft: '12px solid transparent',
          borderRight: '12px solid transparent',
          borderTop: `12px solid ${C.bubble}`,
        }}
      />
    </div>
  </div>
)

/** A box on the raised surface with a small label, like a field in the app. */
export const Field: React.FC<{ id: string; x: number; y: number; w: number; label: string; children: React.ReactNode }> = ({ id, x, y, w, label, children }) => (
  <div id={id} className="part" style={{ position: 'absolute', left: x, top: y - 76 }}>
    <div style={{ height: 28, fontSize: 22, lineHeight: '28px', color: C.text3, marginBottom: 8 }}>{label}</div>
    <div
      style={{
        width: w,
        height: 80,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        padding: '0 22px',
        borderRadius: 12,
        border: `2px solid ${C.border}`,
        background: C.surface,
        fontSize: 30,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
      }}
    >
      {children}
    </div>
  </div>
)
