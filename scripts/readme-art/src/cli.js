import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { render } from "takumi-js";
import { CHIP_SURFACES, SURFACES, outputName } from "./catalog.js";
import { loadFonts } from "./fonts.js";
import { assertPngSize } from "./png.js";
import { printPreviewResult, renderReadmePreviews } from "./preview.js";
import { GLOBAL_CSS, THEMES } from "./tokens.js";
import { Architecture } from "./templates/architecture.jsx";
import { Chip } from "./templates/chips.jsx";
import { CliTerminal } from "./templates/cli-terminal.jsx";
import { Hero } from "./templates/hero.jsx";
import { Nouns } from "./templates/nouns.jsx";
import { PathToValue } from "./templates/path-to-value.jsx";
import { Providers } from "./templates/providers.jsx";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(HERE, "..");
const REPO_ROOT = path.resolve(PKG_ROOT, "../..");
const DEFAULT_OUT = path.join(REPO_ROOT, "assets/readme");
const DEFAULT_PREVIEW_OUT = path.join(DEFAULT_OUT, "previews");
const THEME_NAMES = ["light", "dark"];
const COMMANDS = ["render", "list", "check", "preview"];

const CARDS = {
  hero: Hero,
  architecture: Architecture,
  "path-to-value": PathToValue,
  nouns: Nouns,
  "cli-terminal": CliTerminal,
  providers: Providers,
};

const HELP = `Usage: node scripts/readme-art render [options]
       node scripts/readme-art preview [options]
       node scripts/readme-art --list
       node scripts/readme-art --check

Render Route Ledger README rasters into assets/readme/.
Preview renders local GitHub-flavored HTML (does not load github.com).

Options:
  --out DIR   Output directory (render: <repo>/assets/readme;
              preview: <repo>/assets/readme/previews)
  --list      List visual-contract stems and sizes
  --check     Verify existing PNG dimensions (no write)
  --help      Show this help
`;

function defaultOut(command) {
  return command === "preview" ? DEFAULT_PREVIEW_OUT : DEFAULT_OUT;
}

function parseArgs(argv) {
  const args = argv.slice(2);
  const flags = new Set();
  let out = null;
  const positionals = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") {
      flags.add("help");
      continue;
    }
    if (arg === "--list") {
      flags.add("list");
      continue;
    }
    if (arg === "--check") {
      flags.add("check");
      continue;
    }
    if (arg === "--out") {
      const value = args[i + 1];
      if (!value || value.startsWith("-")) {
        throw new Error("--out requires a directory");
      }
      out = path.resolve(value);
      i += 1;
      continue;
    }
    if (arg.startsWith("-")) {
      throw new Error(`unknown option: ${arg}`);
    }
    positionals.push(arg);
  }
  const command = positionals[0] ?? "render";
  if (positionals.length > 1) {
    throw new Error(`unexpected arguments: ${positionals.slice(1).join(" ")}`);
  }
  if (!COMMANDS.includes(command)) {
    throw new Error(`unknown command: ${command}`);
  }
  return { command, flags, out: out ?? defaultOut(command) };
}

function listSurfaces() {
  const lines = SURFACES.map((surface) => {
    const stem = surface.stem.padEnd(22);
    return `${stem}${surface.width}x${surface.height}`;
  });
  return `${lines.join("\n")}\n`;
}

function expectedSize(surface) {
  return { width: surface.width, height: surface.height };
}

function nodeFor(surface, theme) {
  const Card = CARDS[surface.stem];
  if (Card) {
    return { type: Card, props: { theme }, key: null };
  }
  const chip = CHIP_SURFACES.find((item) => item.stem === surface.stem);
  if (!chip) {
    throw new Error(`no template for ${surface.stem}`);
  }
  return {
    type: Chip,
    props: { theme, label: chip.label, accent: chip.accent },
    key: null,
  };
}

async function renderSurface(surface, themeName, fonts) {
  const theme = THEMES[themeName];
  const bytes = await render(nodeFor(surface, theme), {
    width: surface.width,
    height: surface.height,
    format: "png",
    fonts,
    css: GLOBAL_CSS,
    jsx: { defaultStyles: false },
  });
  assertPngSize(bytes, surface.width, surface.height, `${surface.stem}-${themeName}`);
  return bytes;
}

async function writeAll(outDir, fonts) {
  await mkdir(outDir, { recursive: true });
  const written = [];
  for (const surface of SURFACES) {
    for (const themeName of THEME_NAMES) {
      const name = outputName(surface.stem, themeName);
      const dest = path.join(outDir, name);
      if (path.basename(path.dirname(dest)) === "previews") {
        throw new Error("refusing to write into assets/readme/previews/");
      }
      const bytes = await renderSurface(surface, themeName, fonts);
      await writeFile(dest, bytes);
      written.push({ name, bytes: bytes.length, ...expectedSize(surface) });
    }
  }
  return written;
}

async function checkExisting(outDir) {
  const errors = [];
  for (const surface of SURFACES) {
    for (const themeName of THEME_NAMES) {
      const name = outputName(surface.stem, themeName);
      const dest = path.join(outDir, name);
      try {
        const bytes = await readFile(dest);
        assertPngSize(bytes, surface.width, surface.height, name);
      } catch (error) {
        errors.push(`${name}: ${error instanceof Error ? error.message : error}`);
      }
    }
  }
  if (errors.length > 0) {
    throw new Error(`dimension check failed\n${errors.join("\n")}`);
  }
}

function printWritten(written) {
  for (const file of written) {
    const kb = (file.bytes / 1024).toFixed(1);
    console.log(`${file.name.padEnd(32)} ${file.width}x${file.height}  ${kb} KB`);
  }
  console.log(`wrote ${written.length} rasters`);
}

async function main() {
  let parsed;
  try {
    parsed = parseArgs(process.argv);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
    return;
  }
  if (parsed.flags.has("help")) {
    process.stdout.write(HELP);
    return;
  }
  if (parsed.flags.has("list") || parsed.command === "list") {
    process.stdout.write(listSurfaces());
    return;
  }
  if (parsed.flags.has("check") || parsed.command === "check") {
    await checkExisting(parsed.out);
    console.log(`ok ${SURFACES.length * THEME_NAMES.length} rasters in ${parsed.out}`);
    return;
  }
  if (parsed.command === "preview") {
    const { written, stats } = await renderReadmePreviews({
      readmePath: path.join(REPO_ROOT, "README.md"),
      assetsDir: DEFAULT_OUT,
      outDir: parsed.out,
      pkgRoot: PKG_ROOT,
    });
    printPreviewResult(written, stats, parsed.out);
    return;
  }
  const fonts = await loadFonts();
  const written = await writeAll(parsed.out, fonts);
  printWritten(written);
}

await main();
