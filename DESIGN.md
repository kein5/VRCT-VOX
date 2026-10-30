---
name: VRCT-VOX Dark Studio
description: A quiet navy workspace for conversation and voice control.
colors:
  primary: "#2865dc"
  primary-hover: "#3470e8"
  focus: "#a9ccff"
  canvas: "#111b2c"
  rail: "#0d1625"
  surface: "#18253b"
  border: "#344662"
  text: "#edf3ff"
  secondary-text: "#adbed6"
typography:
  body:
    fontFamily: "Configured UI font, Noto Sans, system-ui, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 400
    lineHeight: 1.5
  heading:
    fontFamily: "inherit"
    fontSize: "2rem"
    fontWeight: 600
rounded:
  control: "8px"
  composer: "12px"
spacing:
  small: "8px"
  medium: "16px"
  large: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "40px"
---

## Overview

**Creative North Star: "Dark Studio"**

The user chose a complete redesign in deep navy and blue on 2026-10-30. Conversation and audio control take precedence over visual effects. Keep familiar chat, settings and native window controls in the existing React/CSS-module application.

**Key Characteristics:**
- A deep rail separates navigation from the conversation workspace.
- Blue identifies primary actions, selected navigation and keyboard focus.
- Shared forms make TTS, RVC and model downloads feel part of the same application.

## Colors

Use the canvas for conversation and settings, the deeper rail for navigation, and raised surfaces for fields. Borders separate working regions without heavy cards. Amber and red retain warning/error meanings; enable state is also expressed by labels and switch position.

## Typography

Keep the user's configured UI font, scaling and log-font preferences. Local Noto/system fallbacks support Japanese without remote font requests. Section headings give long forms a readable hierarchy; technical paths wrap inside their containers.

## Layout

The regular main rail is 240px and the settings rail is 208px. At the existing 800px scaling-aware breakpoint, main navigation uses a 72px icon rail; settings use a 56px rail that expands for focus or hover. Small windows scroll rather than dropping controls. Top status controls can scroll horizontally when necessary.

The conversation occupies the largest region. An empty state explains where to type, and the composer has a blue send action. Settings have a conventional back button, search and aligned sections. Field labels stack below 700px. Dialogs constrain their width to the viewport and keep explicit consent visible.

## Elevation & Depth

Group controls with spacing, alignment and quiet borders. A dim backdrop identifies modal scope. Avoid decorative elevation in routine forms.

## Shapes

Controls have gently curved edges; the composer has a slightly larger radius. Preserve user window-corner preferences.

## Components

Native buttons carry actions and accessible names. Focus rings remain visible, native checkbox state remains recognizable, and select menus use the dark scheme. Settings transfer focus into their navigation and back to the settings trigger. Transitions are short and disabled under reduced-motion preferences.

Quick Chat and the VR panel inherit shared colors without changing input/audio contracts. TTS/RVC/download forms share field, action and status styling. A persistent saved compact-mode preference remains separate from the temporary narrow-window layout.

## Do's and Don'ts

- Do preserve model consent, dirty-form guards, independent switches and stop/mute behavior.
- Do check Japanese labels, long paths, keyboard navigation and narrow windows using production components.
- Do retain the distinction between configured, pending, active and failed states.
- Don't introduce remote fonts or a new UI framework for this redesign.
- Don't imply connection, model readiness or microphone activity through decorative indicators.
