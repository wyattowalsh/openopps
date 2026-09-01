import { FONT_NEON, FONT_XENON } from "../tokens.js";
import { Card, Display, Frame, Kicker } from "./frame.jsx";

const NODES = [
  {
    index: "01",
    label: "sources",
    note: "firm catalogs",
    command: "sources list",
    hop: "pine",
  },
  {
    index: "02",
    label: "boards",
    note: "ATS routes",
    command: "boards list",
    hop: "brass",
  },
  {
    index: "03",
    label: "jobs",
    note: "normalized listings",
    command: "jobs list",
    hop: "pine",
    active: true,
  },
  {
    index: "04",
    label: "export",
    note: "jsonl csv parquet",
    command: "jobs export",
  },
];

function Node({ theme, node }) {
  const active = Boolean(node.active);
  return (
    <Card
      theme={theme}
      active={active}
      pad={18}
      style={{
        flexGrow: 1,
        height: 240,
        justifyContent: "flex-start",
        gap: 28,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div
          style={{
            display: "flex",
            width: 40,
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
        <Display theme={theme} size={30}>
          {node.label}
        </Display>
        <div
          style={{
            display: "flex",
            fontFamily: FONT_NEON,
            fontSize: 15,
            color: theme.ink,
          }}
        >
          {node.note}
        </div>
        <div
          style={{
            display: "flex",
            fontFamily: FONT_XENON,
            fontSize: 14,
            color: theme.muted,
          }}
        >
          openopps {node.command}
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
        width: 36,
        height: 240,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          width: 36,
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
    <Frame theme={theme} pad={28}>
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
      </div>
    </Frame>
  );
}
