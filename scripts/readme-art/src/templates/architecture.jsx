import { FONT_NEON } from "../tokens.js";
import { Card, Display, Frame, Kicker } from "./frame.jsx";

const NODES = [
  { index: "01", label: "sources", note: "catalogs", hop: "pine" },
  { index: "02", label: "boards", note: "firm sites", hop: "brass" },
  { index: "03", label: "jobs", note: "postings", hop: "pine", active: true },
  { index: "04", label: "export", note: "jsonl csv parquet" },
];

function Node({ theme, node }) {
  const active = Boolean(node.active);
  return (
    <Card
      theme={theme}
      active={active}
      pad={22}
      style={{
        flexGrow: 1,
        height: 300,
        justifyContent: "space-between",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div
          style={{
            display: "flex",
            width: 44,
            height: 3,
            backgroundColor: active ? theme.brass : theme.pine,
          }}
        />
        <div
          style={{
            display: "flex",
            fontFamily: FONT_NEON,
            fontSize: 13,
            fontWeight: 600,
            color: theme.muted,
          }}
        >
          {node.index}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Display theme={theme} size={34}>
          {node.label}
        </Display>
        <div
          style={{
            display: "flex",
            fontFamily: FONT_NEON,
            fontSize: 14,
            color: theme.muted,
          }}
        >
          {node.note}
        </div>
      </div>
    </Card>
  );
}

function Hop({ theme, color }) {
  const fill = color === "brass" ? theme.brass : theme.pine;
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexShrink: 0,
        width: 48,
        height: 300,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          width: 48,
          height: 2,
          backgroundColor: fill,
        }}
      />
      <div
        style={{
          position: "absolute",
          display: "flex",
          width: 8,
          height: 8,
          backgroundColor: fill,
        }}
      />
    </div>
  );
}

export function Architecture({ theme }) {
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
        <Kicker theme={theme}>architecture</Kicker>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            flexGrow: 1,
            width: "100%",
          }}
        >
          {NODES.flatMap((node, index) => {
            const items = [
              <Node key={node.label} theme={theme} node={node} />,
            ];
            if (index < NODES.length - 1) {
              items.push(
                <Hop
                  key={`hop-${node.label}`}
                  theme={theme}
                  color={node.hop}
                />,
              );
            }
            return items;
          })}
        </div>
        <div
          style={{
            display: "flex",
            marginTop: 8,
            fontFamily: FONT_NEON,
            fontSize: 14,
            color: theme.muted,
          }}
        >
          sources → boards → jobs → export
        </div>
      </div>
    </Frame>
  );
}
