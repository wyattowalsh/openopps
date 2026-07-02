import { expect, test, type APIRequestContext } from "@playwright/test";

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
	baseURL,
}) => {
	const home = await request.get("/");
	expect(home.ok()).toBe(true);

	await expectOneHopRedirect(request, baseURL, "/jobs", "/");
	await expectFinalPath(request, "/jobs/", "/");
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
	await expectOneHopRedirect(request, baseURL, "/docs/explorer", "/explorer");
	await expectFinalPath(request, "/docs/explorer/", "/explorer");
});

async function expectOneHopRedirect(
	request: APIRequestContext,
	baseURL: string | undefined,
	from: string,
	to: string,
) {
	const response = await request.get(from, { maxRedirects: 0 });
	expect([301, 308]).toContain(response.status());
	expect(
		new URL(response.headers()["location"] ?? "", baseURL ?? "http://localhost")
			.pathname,
	).toBe(to);
}

async function expectFinalPath(
	request: APIRequestContext,
	from: string,
	to: string,
) {
	const response = await request.get(from);
	expect(response.ok()).toBe(true);
	expect(new URL(response.url()).pathname).toBe(to);
}
