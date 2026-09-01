import { FONT_ARGON, FONT_FEATURES, FONT_NEON } from "../tokens.js";

function Tick({ theme, top, left, right, bottom }) {
  const edge = `1px solid ${theme.pine}`;
  return (
    <div
      style={{
        position: "absolute",
        display: "flex",
        width: 14,
        height: 14,
        top,
        left,
        right,
        bottom,
        borderTop: top != null ? edge : "none",
        borderBottom: bottom != null ? edge : "none",
        borderLeft: left != null ? edge : "none",
        borderRight: right != null ? edge : "none",
      }}
    />
  );
}

export function Frame({ theme, pad = 32, ticks = true, children }) {
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        width: "100%",
        height: "100%",
        backgroundColor: theme.paper,
        color: theme.ink,
        padding: pad,
        fontFamily: FONT_NEON,
        fontFeatureSettings: FONT_FEATURES,
        letterSpacing: 0,
      }}
    >
      {ticks ? (
        <>
          <Tick theme={theme} top={16} left={16} />
          <Tick theme={theme} top={16} right={16} />
          <Tick theme={theme} bottom={16} left={16} />
          <Tick theme={theme} bottom={16} right={16} />
        </>
      ) : null}
      {children}
    </div>
  );
}

export function Kicker({ theme, children }) {
  return (
    <div
      style={{
        display: "flex",
        fontFamily: FONT_NEON,
        fontSize: 13,
        fontWeight: 600,
        color: theme.pine,
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

export function Rule({ theme, color, width = 48, height = 2 }) {
  return (
    <div
      style={{
        display: "flex",
        width,
        height,
        backgroundColor: color ?? theme.pine,
      }}
    />
  );
}

export function Card({ theme, active = false, pad = 18, radius = 8, style, children }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        backgroundColor: theme.card,
        border: `1px solid ${active ? theme.brass : theme.border}`,
        borderRadius: radius,
        padding: pad,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Display({ theme, size = 32, style, children }) {
  return (
    <div
      style={{
        display: "flex",
        fontFamily: FONT_ARGON,
        fontSize: size,
        fontWeight: 700,
        color: theme.ink,
        lineHeight: 1.08,
        letterSpacing: 0,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
