import React from 'react'
import { Composition } from 'remotion'
import { LOOP_SECONDS, SIZE } from './parts'
import { Captions } from './scenes/Captions'
import { ChatReading } from './scenes/ChatReading'
import { Speech } from './scenes/Speech'
import { Translate } from './scenes/Translate'
import { VoiceChanger } from './scenes/VoiceChanger'

const FPS = 30

// One composition per feature on the home page. The id is the file name under
// site/public/motion/<lang>/ that the home page plays.
export const scenes = [
  { id: 'translate', component: Translate },
  { id: 'captions', component: Captions },
  { id: 'tts', component: Speech },
  { id: 'voice-changer', component: VoiceChanger },
  { id: 'chat-reading', component: ChatReading },
] as const

export const Root: React.FC = () => (
  <>
    {scenes.map(({ id, component }) => (
      <Composition
        key={id}
        id={id}
        component={component}
        durationInFrames={LOOP_SECONDS * FPS}
        fps={FPS}
        width={SIZE.width}
        height={SIZE.height}
        defaultProps={{ lang: 'ja' as const }}
      />
    ))}
  </>
)
