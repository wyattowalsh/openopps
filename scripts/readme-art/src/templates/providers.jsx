import { FONT_ARGON, FONT_NEON, JOB_CAPABLE_PROVIDERS } from "../tokens.js";
import { Card, Frame, Kicker } from "./frame.jsx";

export function Providers({ theme }) {
  return (
    <Frame theme={theme} pad={28}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "baseline",
            justifyContent: "space-between",
            marginBottom: 12,
          }}
        >
          <Kicker theme={theme}>job-capable providers</Kicker>
          <div
            style={{
              display: "flex",
              fontFamily: FONT_NEON,
              fontSize: 13,
              color: theme.muted,
            }}
          >
            built-in · jobs
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 12,
            flexGrow: 1,
          }}
        >
          {JOB_CAPABLE_PROVIDERS.map((name) => (
            <Card
              key={name}
              theme={theme}
              pad={14}
              style={{
                width: 390,
                height: 88,
                flexDirection: "row",
                alignItems: "center",
                gap: 14,
              }}
            >
              <div
                style={{
                  display: "flex",
                  width: 8,
                  height: 8,
                  backgroundColor: theme.pine,
                  borderRadius: 2,
                }}
              />
              <div
                style={{
                  display: "flex",
                  fontFamily: FONT_ARGON,
                  fontSize: 20,
                  fontWeight: 700,
                  color: theme.ink,
                }}
              >
                {name}
              </div>
            </Card>
          ))}
        </div>
      </div>
    </Frame>
  );
}
