import { EnvReadout } from "../_components/env_readout/EnvReadout";

const tones = { active: "active", pending: "warning", failed: "failed", idle: "neutral" };

// One line at the top of a feature page that says what it is doing now, as an
// environment readout; tone is "active", "pending", "failed" or "idle".
export const StatusLine = ({ tone = "idle", children, actions = null }) =>
    <EnvReadout tone={tones[tone] ?? "neutral"} actions={actions}><p>{children}</p></EnvReadout>;
