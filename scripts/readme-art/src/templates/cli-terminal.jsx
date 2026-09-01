import { FONT_NEON, FONT_XENON } from "../tokens.js";
import { Frame, Kicker } from "./frame.jsx";

const LINES = [
  { kind: "prompt", text: "uv run openopps status" },
  { kind: "blank" },
  { kind: "row", key: "db", value: "local sqlite" },
  { kind: "row", key: "cache", value: "ready" },
  { kind: "row", key: "probe", value: "dry-run by default" },
  { kind: "row", key: "next", value: "openopps sync <source>" },
];

export function CliTerminal({ theme }) {
  return (
    <Frame theme={theme} pad={32}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
        }}
      >
        <Kicker theme={theme}>cli</Kicker>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flexGrow: 1,
            backgroundColor: theme.ink,
            color: theme.paper,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            padding: 22,
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              marginBottom: 16,
              paddingBottom: 12,
              borderBottom: `1px solid ${theme.paper}33`,
            }}
          >
            <div
              style={{
                display: "flex",
                fontFamily: FONT_NEON,
                fontSize: 13,
                fontWeight: 600,
                color: theme.paper,
              }}
            >
              openopps
            </div>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              fontFamily: FONT_XENON,
              fontSize: 20,
            }}
          >
            {LINES.map((line, index) => {
              if (line.kind === "blank") {
                return (
                  <div
                    key={`blank-${index}`}
                    style={{ display: "flex", height: 8 }}
                  />
                );
              }
              if (line.kind === "prompt") {
                return (
                  <div
                    key="prompt"
                    style={{
                      display: "flex",
                      flexDirection: "row",
                      gap: 12,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        color: theme.brass,
                        fontWeight: 600,
                      }}
                    >
                      $
                    </div>
                    <div style={{ display: "flex", color: theme.paper }}>
                      {line.text}
                    </div>
                  </div>
                );
              }
              return (
                <div
                  key={line.key}
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    gap: 28,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      width: 72,
                      color: theme.brass,
                    }}
                  >
                    {line.key}
                  </div>
                  <div style={{ display: "flex", color: theme.paper }}>
                    {line.value}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Frame>
  );
}
