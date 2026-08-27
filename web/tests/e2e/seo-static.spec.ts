import { expect, test } from "@playwright/test";

test("robots and sitemap routes expose the public static surface", async ({
	request,
}) => {
	const indexableResponse = await request.get(
		"/data/openopps-search/jobs-indexable-ids.json",
	);
	expect(indexableResponse.ok()).toBe(true);
	const indexablePayload = (await indexableResponse.json()) as { ids: string[] };

	const robots = await request.get("/robots.txt");
	expect(robots.ok()).toBe(true);
	const robotsText = await robots.text();
	expect(robotsText).toMatch(/Allow:\s*\//);
	expect(robotsText).toMatch(/Disallow:\s*\/api\//);
	expect(robotsText).toContain("/sitemap.xml");
	expect(robotsText).toMatch(/User-Agent:\s*OAI-SearchBot/i);
	expect(robotsText).toMatch(/User-Agent:\s*Claude-SearchBot/i);
	expect(robotsText).toMatch(/User-Agent:\s*PerplexityBot/i);
	expect(robotsText).toMatch(/User-Agent:\s*Googlebot/i);
	expect(robotsText).toMatch(/User-Agent:\s*GPTBot/i);
	expect(robotsText).toMatch(/User-Agent:\s*ClaudeBot/i);
	expect(robotsText).toMatch(/User-Agent:\s*Google-Extended/i);
	expect(robotsText).toMatch(/Host:\s*www\.openopps\.dev/i);
	if (indexablePayload.ids.length > 0) {
		expect(robotsText).toContain("/jobs/sitemap/0.xml");
		const jobsSitemap = await request.get("/jobs/sitemap/0.xml");
		expect(jobsSitemap.ok()).toBe(true);
		const jobsSitemapText = await jobsSitemap.text();
		expect(jobsSitemapText).toContain("/jobs/");
	} else {
		expect(robotsText).not.toContain("/jobs/sitemap/0.xml");
	}

	const sitemap = await request.get("/sitemap.xml");
	expect(sitemap.ok()).toBe(true);
	const sitemapText = await sitemap.text();
	expect(sitemapText).toContain("https://www.openopps.dev/");
	expect(sitemapText).toContain("https://www.openopps.dev/explorer");
	expect(sitemapText).toContain(
		"https://www.openopps.dev/docs/public-data-releases",
	);
	expect(sitemapText).toContain("https://www.openopps.dev/llms.txt");
	expect(sitemapText).toContain("https://www.openopps.dev/llms-full.txt");
	expect(sitemapText).toContain("https://www.openopps.dev/feed.xml");
	expect(sitemapText).toContain("<lastmod>");

	const llms = await request.get("/llms.txt");
	expect(llms.ok()).toBe(true);
	const llmsText = await llms.text();
	expect(llmsText.startsWith("# OpenOpps")).toBe(true);
	expect(llmsText).toContain(">");
	expect(llmsText).toContain("## Product");
	expect(llmsText).toContain("https://www.openopps.dev/");
	expect(llmsText).toContain("https://www.openopps.dev/explorer");
	expect(llmsText).toContain("https://www.openopps.dev/docs");
	expect(llmsText).toContain("/llms.mdx/docs/");
	expect(llmsText).toContain("/feed.xml");

	const feed = await request.get("/feed.xml");
	expect(feed.ok()).toBe(true);
	expect(feed.headers()["content-type"] ?? "").toContain("application/atom+xml");
	const feedText = await feed.text();
	expect(feedText).toContain("http://www.w3.org/2005/Atom");
	expect(feedText).toContain("https://www.openopps.dev/feed.xml");
});

test("home, explorer, and docs emit JSON-LD and describedby", async ({
	page,
}) => {
	await page.goto("/");
	await expect(page.locator('link[rel="describedby"]')).toHaveAttribute(
		"href",
		"https://www.openopps.dev/llms.txt",
	);
	await expect(
		page.locator('link[rel="alternate"][type="application/atom+xml"]').first(),
	).toHaveAttribute("href", "https://www.openopps.dev/feed.xml");
	const homeLd = await page.locator('script[type="application/ld+json"]').first().textContent();
	expect(homeLd).toContain("WebSite");
	expect(homeLd).toContain("SearchAction");
	expect(homeLd).toContain("/?q={search_term_string}");
	expect(homeLd).toContain("Organization");
	expect(homeLd).toContain("Dataset");
	expect(homeLd).toContain("BreadcrumbList");

	await page.goto("/explorer");
	const explorerLd = await page
		.locator('script[type="application/ld+json"]')
		.first()
		.textContent();
	expect(explorerLd).toContain("Dataset");
	expect(explorerLd).toContain("BreadcrumbList");
	expect(explorerLd).toContain("wyattowalsh/openoppsdb");

	await page.goto("/docs");
	const docsLd = await page.locator('script[type="application/ld+json"]').first().textContent();
	expect(docsLd).toContain("BreadcrumbList");
	expect(docsLd).toContain("/docs");
});
