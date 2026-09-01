import { FONT_ARGON, FONT_NEON, FONT_XENON } from "../tokens.js";
import { Card, Frame, Kicker } from "./frame.jsx";

const STEPS = [
  {
    index: "01",
    label: "install",
    detail: "put the CLI on PATH",
    command: "uv tool install openopps",
  },
  {
    index: "02",
    label: "sync / pull",
    detail: "boards become jobs",
    command: "openopps sync <source>",
    active: true,
  },
  {
    index: "03",
    label: "export",
    detail: "jsonl csv parquet sqlite",
    command: "openopps jobs export",
  },
];

export function PathToValue({ theme }) {
  return (
    <Frame theme={theme} pad={24}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
        }}
      >
        <Kicker theme={theme}>path to value</Kicker>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            gap: 14,
            flexGrow: 1,
          }}
        >
          {STEPS.map((step) => (
            <Card
              key={step.index}
              theme={theme}
              active={step.active}
              pad={16}
              style={{
                flexGrow: 1,
                height: "100%",
                justifyContent: "flex-start",
                gap: 18,
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    width: 28,
                    height: 28,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: step.active ? theme.brass : theme.pine,
                    color: theme.paper,
                    fontFamily: FONT_ARGON,
                    fontSize: 13,
                    fontWeight: 700,
                    borderRadius: 4,
                  }}
                >
                  {step.index}
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      fontFamily: FONT_NEON,
                      fontSize: 16,
                      fontWeight: 600,
                      color: theme.ink,
                    }}
                  >
                    {step.label}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      fontFamily: FONT_NEON,
                      fontSize: 13,
                      color: theme.muted,
                    }}
                  >
                    {step.detail}
                  </div>
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  fontFamily: FONT_XENON,
                  fontSize: 16,
                  color: theme.ink,
                }}
              >
                {step.command}
              </div>
            </Card>
          ))}
        </div>
      </div>
    </Frame>
  );
}
