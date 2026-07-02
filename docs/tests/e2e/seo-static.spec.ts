import { expect, test } from "@playwright/test";

test("robots and sitemap routes expose the public static surface", async ({
	request,
}) => {
	const robots = await request.get("/robots.txt");
	expect(robots.ok()).toBe(true);
	const robotsText = await robots.text();
	expect(robotsText).toContain("Allow: /");
	expect(robotsText).toContain("Disallow: /api/");
	expect(robotsText).toContain("/sitemap.xml");
	expect(robotsText).not.toContain("/jobs/sitemap/0.xml");

	const sitemap = await request.get("/sitemap.xml");
	expect(sitemap.ok()).toBe(true);
	const sitemapText = await sitemap.text();
	expect(sitemapText).toContain("https://openopps.dev/");
	expect(sitemapText).toContain("https://openopps.dev/explorer");
});
