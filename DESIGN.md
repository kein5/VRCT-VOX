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
  description-text: "#8d9fb9"
  state-active: "#80acff"
  state-warning: "#cb944f"
  state-failed: "#f08a85"
  readout-rule: "#5b92ff"
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
  category-heading:
    fontSize: "2rem"
    fontWeight: 600
  subheading:
    fontSize: "1.5rem"
    fontWeight: 600
  item-label:
    fontSize: "1.4rem"
    fontWeight: 500
  description:
    fontSize: "1.2rem"
    fontWeight: 400
    lineHeight: 1.6
  readout:
    fontSize: "1.3rem"
    fontWeight: 500
    fontFeature: "tabular-nums"
rounded:
  control: "8px"
  composer: "12px"
  dialog: "12px"
spacing:
  xsmall: "4px"
  small: "8px"
  medium: "16px"
  large: "24px"
  section: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "9px 12px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  env-readout:
    backgroundColor: "{colors.surface}"
    borderLeft: "3px solid {colors.readout-rule}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
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

## Roles in settings

Settings pages use four roles, and each must be recognizable without reading it. The user approved these on 2026-11-01.

| Role | Look | Use |
|---|---|---|
| Category heading | 2rem / 600, text color, 40px above and 16px below, hairline to the right | One per page section (TTS, RVC, Mic) |
| Subheading | 1.5rem / 600, secondary text, 24px above and 8px below, no frame | Groups inside a section (Monitor, Japanese TTS voice) |
| Item label | 1.4rem / 500, text color, wraps | The name of one setting |
| General description | 1.2rem / 400, description text, at most two lines visible; the rest goes in a "詳細" disclosure | What a setting does, true on every PC |
| Environment readout | 1.3rem / 500, tabular numbers, surface background, 3px left rule, 8px radius | What this PC and this session report now: GPU and memory, server state, download progress, model support |

A readout states its condition in words; its color repeats the words (active blue, warning amber, failed red) and never replaces them. Frames are kept for real units, such as one server or engine; groups inside a section are separated by space and a subheading, not by nested borders. One-time setup (model files, servers, downloads) sits in one folded "モデルとサーバー" section per page with a one-line status.

The settings top bar always offers the stop actions: stop TTS (clears the queue) and mute VRCT's voice output. They are quiet until there is something to stop.

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
