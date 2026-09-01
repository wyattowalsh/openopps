import { CHIP_HEIGHT, CHIPS } from "./tokens.js";

export const CARD_SURFACES = [
  { stem: "hero", width: 1280, height: 480 },
  { stem: "architecture", width: 1280, height: 520 },
  { stem: "path-to-value", width: 1280, height: 280 },
  { stem: "nouns", width: 1280, height: 200 },
  { stem: "cli-terminal", width: 1280, height: 360 },
  { stem: "providers", width: 1280, height: 400 },
];

export const CHIP_SURFACES = CHIPS.map((chip) => ({
  stem: chip.stem,
  width: chip.width,
  height: CHIP_HEIGHT,
  label: chip.label,
  accent: chip.accent,
}));

export const SURFACES = [...CARD_SURFACES, ...CHIP_SURFACES];

export function outputName(stem, theme) {
  return `${stem}-${theme}.png`;
}
