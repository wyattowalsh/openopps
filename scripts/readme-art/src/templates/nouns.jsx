import { FONT_ARGON, FONT_NEON } from "../tokens.js";
import { Card, Frame } from "./frame.jsx";

const NOUNS = [
  { label: "sources", note: "catalogs" },
  { label: "boards", note: "firm sites" },
  { label: "jobs", note: "postings", active: true },
  { label: "providers", note: "routes" },
];

export function Nouns({ theme }) {
  return (
    <Frame theme={theme} pad={24}>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          width: "100%",
          height: "100%",
          gap: 16,
        }}
      >
        {NOUNS.map((noun) => (
          <Card
            key={noun.label}
            theme={theme}
            active={noun.active}
            pad={16}
            style={{
              flexGrow: 1,
              height: "100%",
              justifyContent: "space-between",
            }}
          >
            <div
              style={{
                display: "flex",
                width: 36,
                height: 3,
                backgroundColor: noun.active ? theme.brass : theme.pine,
              }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div
                style={{
                  display: "flex",
                  fontFamily: FONT_ARGON,
                  fontSize: 26,
                  fontWeight: 700,
                  color: theme.ink,
                }}
              >
                {noun.label}
              </div>
              <div
                style={{
                  display: "flex",
                  fontFamily: FONT_NEON,
                  fontSize: 14,
                  color: theme.muted,
                }}
              >
                {noun.note}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </Frame>
  );
}
