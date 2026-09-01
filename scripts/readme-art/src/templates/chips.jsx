import { FONT_FEATURES, FONT_NEON } from "../tokens.js";

export function Chip({ theme, label, accent = "pine" }) {
  const bar = accent === "brass" ? theme.brass : theme.pine;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        width: "100%",
        height: "100%",
        backgroundColor: theme.card,
        border: `1px solid ${theme.border}`,
        borderRadius: 6,
        paddingLeft: 10,
        paddingRight: 12,
        fontFamily: FONT_NEON,
        fontFeatureSettings: FONT_FEATURES,
        letterSpacing: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          width: 6,
          height: 18,
          marginRight: 8,
          backgroundColor: bar,
          borderRadius: 2,
        }}
      />
      <div
        style={{
          display: "flex",
          fontSize: 15,
          fontWeight: 600,
          color: theme.ink,
        }}
      >
        {label}
      </div>
    </div>
  );
}
