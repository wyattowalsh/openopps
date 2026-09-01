import { FONT_ARGON, FONT_NEON } from "../tokens.js";
import { Display, Frame, Kicker, Rule } from "./frame.jsx";

const FLOW = ["sources", "boards", "jobs", "export"];

export function Hero({ theme }) {
  return (
    <Frame theme={theme} pad={32}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <Kicker theme={theme}>route ledger</Kicker>
          <Display theme={theme} size={84}>
            OpenOpps
          </Display>
          <div style={{ display: "flex", marginTop: 16 }}>
            <Rule theme={theme} color={theme.brass} width={72} height={3} />
          </div>
          <div
            style={{
              display: "flex",
              marginTop: 22,
              width: "100%",
              fontFamily: FONT_NEON,
              fontSize: 26,
              fontWeight: 400,
              color: theme.ink,
              lineHeight: 1.28,
            }}
          >
            Discover boards, sync public jobs, export a local ledger.
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 16,
          }}
        >
          {FLOW.map((noun, index) => (
            <div
              key={noun}
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 16,
              }}
            >
              <div
                style={{
                  display: "flex",
                  fontFamily: FONT_ARGON,
                  fontSize: 20,
                  fontWeight: 600,
                  color: index === 2 ? theme.brass : theme.ink,
                }}
              >
                {noun}
              </div>
              {index < FLOW.length - 1 ? (
                <div
                  style={{
                    display: "flex",
                    width: 36,
                    height: 2,
                    backgroundColor: index === 1 ? theme.brass : theme.pine,
                  }}
                />
              ) : null}
            </div>
          ))}
          <div
            style={{
              display: "flex",
              marginLeft: "auto",
              fontFamily: FONT_NEON,
              fontSize: 14,
              fontWeight: 600,
              color: theme.muted,
            }}
          >
            CLI
          </div>
        </div>
      </div>
    </Frame>
  );
}
