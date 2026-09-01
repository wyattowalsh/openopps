// Hexes from goals/readme-awesomeify/visual-contract.md (DESIGN.md Route Ledger).

export const LIGHT = {
  paper: "#f7f1df",
  card: "#fff9ea",
  ink: "#1d281f",
  pine: "#2f6f50",
  brass: "#d99629",
  border: "#cfc1a6",
  muted: "#575044",
};

export const DARK = {
  paper: "#1d281f",
  card: "#263a28",
  ink: "#f7f1df",
  pine: "#4a9a68",
  brass: "#e0a84a",
  border: "#3d4a38",
  muted: "#cfc1a6",
};

export const THEMES = { light: LIGHT, dark: DARK };

export const FONT_FEATURES = '"ss01" 1, "ss02" 1, "ss03" 1, "calt" 1, "liga" 1';

export const FONT_ARGON = "Monaspace Argon";
export const FONT_NEON = "Monaspace Neon";
export const FONT_XENON = "Monaspace Xenon";

export const GLOBAL_CSS = `* {
  box-sizing: border-box;
  letter-spacing: 0;
  font-feature-settings: ${FONT_FEATURES};
}`;

export const JOB_CAPABLE_PROVIDERS = [
  "Ashby",
  "Greenhouse",
  "Lever",
  "Workday",
  "Workable",
  "Teamtailor",
  "BambooHR",
  "Rippling",
  "WP Job Manager",
];

export const CHIPS = [
  { stem: "chip-cli", label: "CLI", width: 96, accent: "pine" },
  { stem: "chip-uv", label: "uv", width: 84, accent: "pine" },
  { stem: "chip-typer", label: "Typer", width: 116, accent: "pine" },
  { stem: "chip-python", label: "Python", width: 128, accent: "pine" },
  { stem: "chip-route-ledger", label: "Route Ledger", width: 188, accent: "brass" },
];

export const CHIP_HEIGHT = 44;
