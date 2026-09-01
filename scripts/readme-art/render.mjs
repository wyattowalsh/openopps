#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.join(here, "dist/cli.mjs");

await mkdir(path.dirname(outfile), { recursive: true });
await esbuild.build({
  absWorkingDir: here,
  entryPoints: ["src/cli.js"],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node24",
  outfile,
  jsx: "automatic",
  jsxImportSource: "react",
  packages: "external",
  logLevel: "silent",
});

await import(pathToFileURL(outfile).href);
