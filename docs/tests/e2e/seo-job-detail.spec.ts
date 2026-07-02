import { expect, test } from "@playwright/test";

let firstJobPath: string;

test.beforeAll(async ({ request }) => {
	const idsResponse = await request.get("/data/openopps-search/jobs-detail-ids.json");
	expect(idsResponse.ok()).toBe(true);
	const idsPayload = (await idsResponse.json()) as { ids: string[] };
	expect(idsPayload.ids.length).toBeGreaterThan(0);
	firstJobPath = `/jobs/${encodeURIComponent(idsPayload.ids[0])}`;
});

test("thin job detail pages are noindexed and omit JobPosting", async ({
	page,
}) => {
	await page.goto(firstJobPath);
	await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
	await expect(
		page.getByRole("link", { name: /open in jobs board/i }),
	).toBeVisible();

	await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
		"content",
		/noindex/,
	);
	await expect(page.locator('link[rel="canonical"]')).toHaveCount(0);
	await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(0);
});
