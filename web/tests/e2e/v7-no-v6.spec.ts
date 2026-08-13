import { expect, test } from "@playwright/test";

const V7_JOB_ID = process.env.OPENOPPS_E2E_V7_JOB_ID?.trim();
const V7_BROWSER_ORIGIN =
	process.env.NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_ORIGIN?.trim();
const V7_BROWSER_CHANNEL =
	process.env.NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_CHANNEL?.trim();
const ALLOW_SELF_SIGNED_HTTPS =
	process.env.OPENOPPS_E2E_V7_ALLOW_SELF_SIGNED_HTTPS?.trim() === "1";

function hasV7BrowserFixture() {
	if (!V7_JOB_ID || V7_BROWSER_CHANNEL !== "production") {
		return false;
	}
	try {
		return new URL(V7_BROWSER_ORIGIN ?? "").protocol === "https:";
	} catch {
		return false;
	}
}

test.describe("v7 public data without the legacy v6 tree", () => {
	test.use({ ignoreHTTPSErrors: ALLOW_SELF_SIGNED_HTTPS });
	test.skip(
		!hasV7BrowserFixture(),
		"requires an isolated HTTPS v7 fixture, OPENOPPS_E2E_V7_JOB_ID, and NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_{ORIGIN,CHANNEL}=.../production at build and test time",
	);

	test("build routes and browser search use only the pinned v7 release", async ({
		page,
		request,
	}) => {
		test.setTimeout(90_000);
		const legacyBrowserRequests: string[] = [];
		const releaseBrowserRequests: string[] = [];
		let serverSearchRequests = 0;
		page.on("request", (browserRequest) => {
			const pathname = new URL(browserRequest.url()).pathname;
			if (pathname.startsWith("/data/openopps-search/")) {
				legacyBrowserRequests.push(pathname);
			}
			if (pathname.startsWith("/releases/")) {
				releaseBrowserRequests.push(pathname);
			}
			if (pathname === "/api/jobs/search") {
				serverSearchRequests += 1;
			}
		});

		const legacyManifest = await request.get(
			"/data/openopps-search/manifest.json",
		);
		expect(legacyManifest.status()).toBe(404);

		const pointerResponse = await request.get("/channels/production.json");
		expect(pointerResponse.ok()).toBe(true);
		const pointer = (await pointerResponse.json()) as {
			releaseId: string;
			manifestPath: string;
		};
		expect(pointer.releaseId).toMatch(/^[a-f0-9]{64}$/);
		expect(pointer.manifestPath).toBe(
			`releases/${pointer.releaseId}/manifest.json`,
		);
		const releaseManifest = await request.get(`/${pointer.manifestPath}`);
		expect(releaseManifest.ok()).toBe(true);

		const detailApi = await request.get(
			`/api/jobs/detail?id=${encodeURIComponent(V7_JOB_ID!)}`,
		);
		expect(detailApi.ok()).toBe(true);
		expect(await detailApi.json()).toMatchObject({ id: V7_JOB_ID });

		await page.goto(`/jobs/${encodeURIComponent(V7_JOB_ID!)}`);
		await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
		await expect(
			page.getByRole("link", { name: /open in jobs board/i }),
		).toBeVisible();

		const sitemap = await request.get("/sitemap.xml");
		expect(sitemap.ok()).toBe(true);
		expect(await sitemap.text()).toContain("https://openopps.dev/");
		const jobsSitemap = await request.get("/jobs/sitemap/0.xml");
		expect(jobsSitemap.ok()).toBe(true);
		expect(await jobsSitemap.text()).toContain(
			`/jobs/${encodeURIComponent(V7_JOB_ID!)}`,
		);

		await page.goto("/");
		const search = page.getByLabel("Search jobs");
		await expect(search).toBeVisible({ timeout: 30_000 });
		await search.fill("platform");
		await expect(
			page.getByRole("status").filter({ hasText: /searching jobs/i }),
		).toBeHidden({ timeout: 45_000 });
		await expect(
			page
				.getByRole("listbox", { name: /open jobs results/i })
				.getByRole("option")
				.first(),
		).toBeVisible({ timeout: 45_000 });

		expect(releaseBrowserRequests.length).toBeGreaterThan(0);
		expect(legacyBrowserRequests).toEqual([]);
		expect(serverSearchRequests).toBe(0);
	});
});
