import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

function fontFile(pkg, file) {
  const pkgJson = fileURLToPath(import.meta.resolve(`${pkg}/package.json`));
  return path.join(path.dirname(pkgJson), "files", file);
}

async function entry(name, weight, pkg, file) {
  return {
    name,
    weight,
    style: "normal",
    generic: "monospace",
    data: await readFile(fontFile(pkg, file)),
  };
}

export async function loadFonts() {
  return Promise.all([
    entry(
      "Monaspace Argon",
      400,
      "@fontsource/monaspace-argon",
      "monaspace-argon-latin-400-normal.woff2",
    ),
    entry(
      "Monaspace Argon",
      600,
      "@fontsource/monaspace-argon",
      "monaspace-argon-latin-600-normal.woff2",
    ),
    entry(
      "Monaspace Argon",
      700,
      "@fontsource/monaspace-argon",
      "monaspace-argon-latin-700-normal.woff2",
    ),
    entry(
      "Monaspace Neon",
      400,
      "@fontsource/monaspace-neon",
      "monaspace-neon-latin-400-normal.woff2",
    ),
    entry(
      "Monaspace Neon",
      600,
      "@fontsource/monaspace-neon",
      "monaspace-neon-latin-600-normal.woff2",
    ),
    entry(
      "Monaspace Xenon",
      400,
      "@fontsource/monaspace-xenon",
      "monaspace-xenon-latin-400-normal.woff2",
    ),
    entry(
      "Monaspace Xenon",
      600,
      "@fontsource/monaspace-xenon",
      "monaspace-xenon-latin-600-normal.woff2",
    ),
  ]);
}
