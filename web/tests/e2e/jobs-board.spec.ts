import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function waitForFirstJob(page: Page) {
	const firstJob = page
		.getByRole("listbox", { name: /open jobs results/i })
		.getByRole("option")
		.first();
	await expect(firstJob).toBeVisible({ timeout: 45_000 });
	return firstJob;
}

/** Wait until the live status is no longer "Searching jobs." */
async function waitForJobsSearchSettled(page: Page, timeout = 45_000) {
	const searching = page.getByRole("status").filter({ hasText: /searching jobs/i });
	await expect(searching).toBeHidden({ timeout });
}

async function searchForFirstJob(page: Page, query = "platform") {
	const search = page.getByLabel("Search jobs");
	await expect(search).toBeVisible({ timeout: 30_000 });
	// Register before fill: nuqs debounces URL updates (~200ms) then fetches.
	const searchResponse = page.waitForResponse(
		(response) =>
			response.url().includes("/api/jobs/search") &&
			response.ok() &&
			new URL(response.url()).searchParams.get("q") === query,
		{ timeout: 45_000 },
	);
	await search.fill(query);
	await searchResponse;
	await waitForJobsSearchSettled(page);
	return waitForFirstJob(page);
}

test("jobs board supports local workflow controls without analytics", async ({
	page,
}) => {
	test.setTimeout(90_000);
	const consoleErrors: string[] = [];
	const telemetryRequests: string[] = [];
	page.on("console", (message) => {
		if (message.type() === "error") {
			consoleErrors.push(message.text());
		}
	});
	await page.route("**/api/telemetry", async (route) => {
		telemetryRequests.push(route.request().url());
		await route.abort();
	});

	await page.goto("/");
	await expect(
		page.getByRole("button", { name: /save current search/i }),
	).toBeVisible();
	const firstJob = await searchForFirstJob(page);

	await page.getByRole("button", { name: /save current search/i }).click();
	// hasText scopes to the details node; page.getByText inside filter({has}) is not reliable.
	const savedDetails = page.locator("details").filter({ hasText: "Saved searches" });
	await expect(savedDetails).toBeVisible({ timeout: 20_000 });
	await savedDetails.locator("summary").click();
	await expect(savedDetails).toHaveAttribute("open", "");
	// Full-baseline counts resolve asynchronously (syncing → N new or changed).
	await expect(
		page.getByText(/new or changed|syncing|full baseline/i).first(),
	).toBeVisible({ timeout: 20_000 });

	await firstJob.click();
	const isMobile = (page.viewportSize()?.width ?? 1280) < 768;
	const previewDialog = page.getByRole("dialog", { name: /job preview/i });
	if (isMobile) {
		// Mobile uses a sheet/dialog; desktop keeps an inline preview pane.
		await expect(previewDialog).toBeVisible({ timeout: 15_000 });
	} else {
		await expect(previewDialog).toHaveCount(0);
		expect(await page.evaluate(() => document.body.style.overflow)).not.toBe(
			"hidden",
		);
	}
	await expect(page.getByRole("button", { name: /^save$/i })).toBeVisible();
	await page.getByRole("button", { name: /^save$/i }).click();
	await expect(page.getByText("saved").first()).toBeVisible();
	const closePreviewButton = page.getByRole("button", {
		name: /close job preview/i,
	});
	if (await closePreviewButton.isVisible()) {
		await closePreviewButton.click();
	}

	await page.getByRole("button", { name: /open app settings/i }).click();
	await expect(page.getByRole("dialog", { name: /app settings/i })).toBeVisible();
	await expect(page.getByText("Local workflow data stays in this browser.")).toBeVisible();
	await expect(page.getByLabel(/hide viewed jobs/i )).toBeVisible();
	await page.getByRole("button", { name: /export json/i }).click();
	await expect(page.getByLabel(/exported local data json/i)).toHaveValue(
		/"source": "openopps\.jobs\.local"/,
	);
	await page.keyboard.press("Escape");
	await expect(page.getByRole("dialog", { name: /app settings/i })).toBeHidden();

	expect(consoleErrors).toEqual([]);
	expect(telemetryRequests).toEqual([]);
});

test("jobs board results support keyboard preview activation", async ({ page }) => {
	test.setTimeout(90_000);
	await page.goto("/");
	await searchForFirstJob(page);
	// Ensure loading status has cleared before keyboard focus transfer.
	await waitForJobsSearchSettled(page);

	const list = page.getByRole("listbox", { name: /open jobs results/i });
	await list.focus();
	await page.keyboard.press("ArrowDown");
	await expect(list.getByRole("option").first()).toHaveAttribute(
		"data-focused",
		"true",
		{ timeout: 10_000 },
	);

	await page.keyboard.press("Enter");
	await expect(page.getByRole("button", { name: /^save$/i })).toBeVisible({
		timeout: 15_000,
	});
	await expect(
		page.getByRole("button", { name: /close job preview/i }),
	).toBeVisible({ timeout: 15_000 });
});

test("jobs board searches without browser chunk downloads", async ({ page }) => {
	test.setTimeout(90_000);
	let browserChunkRequests = 0;
	await page.route("**/data/openopps-search/jobs/chunks/*.json", async (route) => {
		browserChunkRequests += 1;
		await route.continue();
	});

	await page.goto("/");

	await searchForFirstJob(page, "platform");

	expect(browserChunkRequests).toBe(0);
});

test("jobs board removes all-indexed mode from the active filter chip", async ({
	page,
}) => {
	test.setTimeout(90_000);
	await page.goto("/");
	await searchForFirstJob(page, "platform");

	const allIndexedSearch = page.waitForResponse(
		(response) => {
			if (!response.url().includes("/api/jobs/search") || !response.ok()) {
				return false;
			}
			return new URL(response.url()).searchParams.get("all") === "1";
		},
		{ timeout: 60_000 },
	);
	await page.getByRole("button", { name: /^All$/i }).click();
	const chip = page.getByRole("button", {
		name: /remove all indexed filter/i,
	});
	await expect(chip).toBeVisible({ timeout: 15_000 });
	// nuqs serializes booleans as true/false in the page URL; API still uses all=1.
	await expect(page).toHaveURL(/[?&]all=(true|1)(?:&|$)/, { timeout: 15_000 });
	await allIndexedSearch;

	const clearedSearch = page.waitForResponse(
		(response) => {
			if (!response.url().includes("/api/jobs/search") || !response.ok()) {
				return false;
			}
			return new URL(response.url()).searchParams.get("all") === null;
		},
		{ timeout: 60_000 },
	);
	await chip.click();
	const response = await clearedSearch;

	expect(new URL(response.url()).searchParams.get("all")).toBeNull();
	await expect(chip).toBeHidden();
	await expect(page.getByRole("button", { name: /^All$/i })).toHaveAttribute(
		"aria-pressed",
		"false",
	);
});
