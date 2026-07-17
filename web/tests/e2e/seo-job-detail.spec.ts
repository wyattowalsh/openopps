import { expect, test } from "@playwright/test";

let thinJobPath: string | undefined;

test.beforeAll(async ({ request }) => {
	const idsResponse = await request.get("/data/openopps-search/jobs-detail-ids.json");
	expect(idsResponse.ok()).toBe(true);
	const idsPayload = (await idsResponse.json()) as { ids: string[] };
	expect(idsPayload.ids.length).toBeGreaterThan(0);
	const indexableResponse = await request.get(
		"/data/openopps-search/jobs-indexable-ids.json",
	);
	expect(indexableResponse.ok()).toBe(true);
	const indexablePayload = (await indexableResponse.json()) as { ids: string[] };
	const indexableIds = new Set(indexablePayload.ids);
	const thinJobId = idsPayload.ids.find((id) => !indexableIds.has(id));
	thinJobPath = thinJobId ? `/jobs/${encodeURIComponent(thinJobId)}` : undefined;
});

test("thin job detail pages are noindexed and omit JobPosting", async ({
page,
}) => {
	test.skip(!thinJobPath, "generated snapshot has no non-indexable job details");

	await page.goto(thinJobPath!);
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
