import { expect, test } from "@playwright/test";

let firstJobPath: string;

test.beforeAll(async ({ request }) => {
	const idsResponse = await request.get("/data/openopps-search/jobs-detail-ids.json");
	expect(idsResponse.ok()).toBe(true);
	const idsPayload = (await idsResponse.json()) as { ids: string[] };
	expect(idsPayload.ids.length).toBeGreaterThan(0);
	firstJobPath = `/jobs/${encodeURIComponent(idsPayload.ids[0])}`;
});

test("v1 public routes use canonical board and explorer URLs", async ({
	request,
}) => {
	const home = await request.get("/");
	expect(home.ok()).toBe(true);

	const bareJobs = await request.get("/jobs", { maxRedirects: 0 });
	expect(bareJobs.status()).toBe(404);
});

test("job detail routes remain addressable under /jobs/:id", async ({ page }) => {
	await page.goto(firstJobPath);

	await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
	await expect(
		page.getByRole("link", { name: /open in jobs board/i }),
	).toBeVisible();
	expect(new URL(page.url()).pathname).toBe(firstJobPath);
});

test("legacy docs explorer route redirects to the canonical explorer", async ({
	request,
	baseURL,
}) => {
	const response = await request.get("/docs/explorer", { maxRedirects: 0 });

	expect([301, 308]).toContain(response.status());
	expect(new URL(response.headers()["location"] ?? "", baseURL).pathname).toBe(
		"/explorer",
	);
});
