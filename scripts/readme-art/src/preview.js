import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { marked } from "marked";
import { chromium } from "playwright";
import { pngSize } from "./png.js";

export const PREVIEW_FILES = ["readme-light.png", "readme-dark.png"];
export const PREVIEW_VIEWPORT = { width: 1280, height: 800 };
export const RAW_ASSET_PREFIX =
  "https://raw.githubusercontent.com/wyattowalsh/openopps/main/assets/readme/";

const THEMES = ["light", "dark"];
const SHIELDS_ORIGIN = "https://img.shields.io/";

function githubMarkdownCssPath(pkgRoot) {
  return path.join(pkgRoot, "node_modules/github-markdown-css/github-markdown.css");
}

export function isGithubHost(urlString) {
  try {
    const { hostname } = new URL(urlString);
    return (
      hostname === "github.com" ||
      hostname.endsWith(".github.com") ||
      hostname === "githubusercontent.com" ||
      hostname.endsWith(".githubusercontent.com") ||
      hostname === "githubassets.com" ||
      hostname.endsWith(".githubassets.com")
    );
  } catch {
    return false;
  }
}

export function isPassthroughUrl(urlString) {
  return (
    urlString === "about:blank" ||
    urlString.startsWith("about:") ||
    urlString.startsWith("data:") ||
    urlString.startsWith("file:") ||
    urlString.startsWith("blob:")
  );
}

export function localReadmeAssetPath(urlString, assetsDir) {
  let pathname = urlString;
  try {
    pathname = decodeURIComponent(new URL(urlString).pathname);
  } catch {
    pathname = urlString.split(/[?#]/, 1)[0];
  }
  const marker = "/assets/readme/";
  const idx = pathname.lastIndexOf(marker);
  const tail =
    idx >= 0
      ? pathname.slice(idx + marker.length)
      : urlString.startsWith(RAW_ASSET_PREFIX)
        ? urlString.slice(RAW_ASSET_PREFIX.length)
        : "";
  const name = tail.split(/[?#]/, 1)[0];
  if (!name || name.includes("/") || name.includes("..") || !name.endsWith(".png")) {
    return null;
  }
  return path.join(assetsDir, name);
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function shieldLabel(urlString) {
  const url = new URL(urlString);
  const fromQuery = url.searchParams.get("label");
  if (fromQuery) {
    return fromQuery;
  }
  const route = url.pathname;
  if (route.includes("/github/actions/workflow/status/")) {
    return "CI";
  }
  if (route.startsWith("/pypi/v/")) {
    return "PyPI";
  }
  if (route.startsWith("/github/license/")) {
    return "License";
  }
  if (route.includes("/badge/python")) {
    return "Python 3.12+";
  }
  return "badge";
}

export function shieldStubSvg(urlString) {
  const label = shieldLabel(urlString).toUpperCase();
  const width = Math.max(80, 16 + label.length * 8);
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="28" role="img" aria-label="${escapeXml(label)}">
  <rect width="${width}" height="28" fill="#555"/>
  <text x="${width / 2}" y="19" fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" font-weight="700" text-anchor="middle">${escapeXml(label)}</text>
</svg>
`;
}

export function markdownToHtml(markdown) {
  const html = marked.parse(markdown, { gfm: true, async: false });
  if (typeof html !== "string") {
    throw new Error("expected synchronous GitHub-flavored markdown parse");
  }
  return html;
}

export function buildPreviewHtml(bodyHtml, githubCss, baseHref) {
  const baseTag = baseHref ? `  <base href="${baseHref}">\n` : "";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
${baseTag}  <title>OpenOpps README preview</title>
  <style>
${githubCss}
    html, body {
      margin: 0;
      background-color: #ffffff;
      color-scheme: light dark;
    }
    @media (prefers-color-scheme: dark) {
      html, body {
        background-color: #0d1117;
      }
    }
    .markdown-body {
      box-sizing: border-box;
      min-width: 200px;
      max-width: 1012px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }
    .markdown-body p[align="center"],
    .markdown-body div[align="center"] {
      text-align: center;
    }
    .markdown-body picture {
      max-width: 100%;
    }
    .markdown-body img {
      max-width: 100%;
      height: auto;
    }
  </style>
</head>
<body>
  <article class="markdown-body">
${bodyHtml}
  </article>
</body>
</html>
`;
}

async function installLocalRoutes(context, assetsDir, stats) {
  await context.route("**/*", async (route) => {
    const url = route.request().url();
    if (isPassthroughUrl(url)) {
      stats.passthrough += 1;
      await route.continue();
      return;
    }
    if (isGithubHost(url) && !localReadmeAssetPath(url, assetsDir)) {
      stats.blockedGithub += 1;
      await route.abort("blockedbyclient");
      return;
    }
    const assetPath = localReadmeAssetPath(url, assetsDir);
    if (assetPath) {
      const body = await readFile(assetPath);
      stats.assets += 1;
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body,
      });
      return;
    }
    if (url.startsWith(SHIELDS_ORIGIN)) {
      stats.shields += 1;
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml; charset=utf-8",
        body: shieldStubSvg(url),
      });
      return;
    }
    stats.blockedOther += 1;
    await route.abort("blockedbyclient");
  });
}

async function waitForImages(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    const images = [...document.images];
    await Promise.all(
      images.map((image) => {
        if (image.complete && image.naturalWidth > 0) {
          return null;
        }
        return new Promise((resolve) => {
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", resolve, { once: true });
        });
      }),
    );
  });
}

async function assertImagesLoaded(page) {
  const broken = await page.evaluate(() =>
    [...document.images]
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => image.currentSrc || image.src),
  );
  if (broken.length > 0) {
    throw new Error(`preview images failed to load:\n${broken.join("\n")}`);
  }
}

async function screenshotTheme(browser, html, assetsDir, colorScheme, dest, stats) {
  const context = await browser.newContext({
    viewport: PREVIEW_VIEWPORT,
    deviceScaleFactor: 1,
    colorScheme,
    reducedMotion: "reduce",
    serviceWorkers: "block",
    javaScriptEnabled: true,
  });
  try {
    await installLocalRoutes(context, assetsDir, stats);
    const page = await context.newPage();
    await page.setContent(html, { waitUntil: "load" });
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    await waitForImages(page);
    await assertImagesLoaded(page);
    await page.screenshot({
      path: dest,
      fullPage: true,
      type: "png",
      animations: "disabled",
      caret: "hide",
      scale: "css",
    });
  } finally {
    await context.close();
  }
}

function chromiumMissingMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("Executable doesn't exist")) {
    return "Playwright Chromium is not installed. Run: pnpm --dir scripts/readme-art exec playwright install chromium";
  }
  return message;
}

export async function renderReadmePreviews({
  readmePath,
  assetsDir,
  outDir,
  pkgRoot,
}) {
  const markdown = await readFile(readmePath, "utf8");
  const githubCss = await readFile(githubMarkdownCssPath(pkgRoot), "utf8");
  const repoRoot = path.dirname(readmePath);
  const baseHref = pathToFileURL(`${repoRoot}${path.sep}`).href;
  const html = buildPreviewHtml(markdownToHtml(markdown), githubCss, baseHref);
  await mkdir(outDir, { recursive: true });

  const stats = {
    passthrough: 0,
    assets: 0,
    shields: 0,
    blockedGithub: 0,
    blockedOther: 0,
    leakedGithub: 0,
  };

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: ["--hide-scrollbars", "--disable-lcd-text", "--font-render-hinting=none"],
    });
  } catch (error) {
    throw new Error(chromiumMissingMessage(error));
  }

  const written = [];
  try {
    for (const theme of THEMES) {
      const name = `readme-${theme}.png`;
      const dest = path.join(outDir, name);
      if (path.dirname(path.resolve(dest)) === path.resolve(assetsDir)) {
        throw new Error(
          "refusing to write preview screenshots into assets/readme/ (use assets/readme/previews/)",
        );
      }
      await screenshotTheme(browser, html, assetsDir, theme, dest, stats);
      const bytes = await readFile(dest);
      const size = pngSize(bytes);
      written.push({ name, bytes: bytes.length, ...size });
    }
  } finally {
    await browser.close();
  }

  if (stats.leakedGithub > 0) {
    throw new Error("preview attempted to load github.com");
  }

  return { written, stats };
}

export function printPreviewResult(written, stats, outDir) {
  for (const file of written) {
    const kb = (file.bytes / 1024).toFixed(1);
    console.log(`${file.name.padEnd(32)} ${file.width}x${file.height}  ${kb} KB`);
  }
  console.log(
    `wrote ${written.length} previews in ${outDir} (github.com not loaded; assets=${stats.assets} shields=${stats.shields} blocked=${stats.blockedGithub + stats.blockedOther})`,
  );
}
