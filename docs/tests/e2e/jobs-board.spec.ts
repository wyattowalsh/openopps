import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function waitForFirstJob(page: Page) {
	const firstJob = page
		.getByRole("listbox", { name: /open jobs results/i })
		.getByRole("option")
		.first();
	await expect(firstJob).toBeVisible({ timeout: 30_000 });
	return firstJob;
}

async function searchForFirstJob(page: Page, query = "platform") {
	const searchResponse = page.waitForResponse(
		(response) => response.url().includes("/api/jobs/search") && response.ok(),
		{ timeout: 30_000 },
	);
	await page.getByLabel("Search jobs").fill(query);
	await searchResponse;
	return waitForFirstJob(page);
}

test("jobs board supports local workflow controls without analytics", async ({
	page,
}) => {
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
	const savedDetails = page.locator("details").filter({
		has: page.getByText("Saved searches", { exact: true }),
	});
	await expect(savedDetails).toBeVisible({ timeout: 20_000 });
	await savedDetails.locator("summary").click();
	await expect(savedDetails).toHaveAttribute("open", "");
	// Full-baseline counts resolve asynchronously (syncing → N new or changed).
	await expect(
		page.getByText(/new or changed|syncing|full baseline/i).first(),
	).toBeVisible({ timeout: 20_000 });

	await firstJob.click();
	await expect(page.getByRole("dialog", { name: /job preview/i })).toHaveCount(0);
	expect(await page.evaluate(() => document.body.style.overflow)).not.toBe(
		"hidden",
	);
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
	await expect(page.getByLabel(/hide viewed jobs/i)).toBeVisible();
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
	await page.goto("/");
	await searchForFirstJob(page);

	const list = page.getByRole("listbox", { name: /open jobs results/i });
	await list.focus();
	await page.keyboard.press("ArrowDown");
	await expect(list.getByRole("option").first()).toHaveAttribute(
		"data-focused",
		"true",
	);

	await page.keyboard.press("Enter");
	await expect(page.getByRole("button", { name: /^save$/i })).toBeVisible();
	await expect(
		page.getByRole("button", { name: /close job preview/i }),
	).toBeVisible();
});

test("jobs board searches without browser chunk downloads", async ({ page }) => {
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
	const searchUrls: string[] = [];
	page.on("response", (response) => {
		if (response.url().includes("/api/jobs/search") && response.ok()) {
			searchUrls.push(response.url());
		}
	});

	await page.goto("/");
	await searchForFirstJob(page, "platform");

	await page.getByRole("button", { name: /^All$/i }).click();
	const chip = page.getByRole("button", {
		name: /remove all indexed filter/i,
	});
	await expect(chip).toBeVisible();
	await expect
		.poll(() => searchUrls.some((url) => new URL(url).searchParams.get("all") === "1"))
		.toBe(true);

	const clearedSearch = page.waitForResponse(
		(response) => {
			if (!response.url().includes("/api/jobs/search") || !response.ok()) {
				return false;
			}
			return new URL(response.url()).searchParams.get("all") === null;
		},
		{ timeout: 30_000 },
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
