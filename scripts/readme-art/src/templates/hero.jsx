import { FONT_ARGON, FONT_NEON, FONT_XENON } from "../tokens.js";
import { Card, Display, Frame, Kicker, Rule } from "./frame.jsx";

const FLOW = ["sources", "boards", "jobs", "export"];

export function Hero({ theme }) {
  return (
    <Frame theme={theme} pad={32}>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          width: "100%",
          height: "100%",
          gap: 28,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flexGrow: 1,
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column" }}>
            <Kicker theme={theme}>route ledger</Kicker>
            <Display theme={theme} size={72}>
              OpenOpps
            </Display>
            <div style={{ display: "flex", marginTop: 14 }}>
              <Rule theme={theme} color={theme.brass} width={72} height={3} />
            </div>
            <div
              style={{
                display: "flex",
                marginTop: 18,
                maxWidth: 640,
                fontFamily: FONT_NEON,
                fontSize: 22,
                fontWeight: 400,
                color: theme.ink,
                lineHeight: 1.3,
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
              gap: 14,
            }}
          >
            {FLOW.map((noun, index) => (
              <div
                key={noun}
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 14,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    fontFamily: FONT_ARGON,
                    fontSize: 18,
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
                      width: 28,
                      height: 2,
                      backgroundColor: index === 1 ? theme.brass : theme.pine,
                    }}
                  />
                ) : null}
              </div>
            ))}
          </div>
        </div>
        <Card
          theme={theme}
          pad={18}
          style={{
            width: 420,
            flexShrink: 0,
            justifyContent: "flex-start",
            gap: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              fontFamily: FONT_NEON,
              fontSize: 12,
              fontWeight: 600,
              color: theme.pine,
            }}
          >
            CLI
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              fontFamily: FONT_XENON,
              fontSize: 16,
              color: theme.ink,
            }}
          >
            <div style={{ display: "flex" }}>$ uv tool install openopps</div>
            <div style={{ display: "flex" }}>$ openopps sync a16z</div>
            <div style={{ display: "flex" }}>$ openopps jobs export</div>
          </div>
        </Card>
      </div>
    </Frame>
  );
}
