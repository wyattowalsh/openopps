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

async function searchForFirstJob(page: Page, query = "platform") {
	const search = page.getByLabel("Search jobs");
	await expect(search).toBeVisible({ timeout: 30_000 });
	await waitForFirstJob(page);
	await search.fill(query);
	await expect(search).toHaveValue(query);
	await expect(page).toHaveURL(
		(url) => url.searchParams.get("q") === query,
		{ timeout: 15_000 },
	);
	return waitForFirstJob(page);
}

test("jobs board lists latest open jobs without a query", async ({ page }) => {
	test.setTimeout(90_000);
	await page.goto("/");
	await waitForFirstJob(page);
	await expect(page.getByLabel("Search jobs")).toHaveValue("");
	await expect(page).not.toHaveURL(/[?&]q=/);
	await expect(
		page.getByRole("heading", { name: "Search or filter open jobs" }),
	).toHaveCount(0);
	await expect(page.getByText("default view")).toBeVisible();
	await expect(page.getByText("Searching...")).toHaveCount(0);
});

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
	const saveSearch = page.getByRole("button", { name: /save current search/i });
	await expect(saveSearch).toBeVisible();
	const firstJob = await searchForFirstJob(page);
	await expect(saveSearch).toBeEnabled({ timeout: 15_000 });

	await saveSearch.click();
	// hasText scopes to the details node; page.getByText inside filter({has}) is not reliable.
	const savedDetails = page.locator("details").filter({ hasText: "Saved searches" });
	await expect(savedDetails).toBeVisible({ timeout: 20_000 });
	await savedDetails.locator("summary").click();
	await expect(savedDetails).toHaveAttribute("open", "");
	// A page-sized save cannot claim a complete full-index baseline. The user must
	// explicitly review it before any "new" count can be presented as authoritative.
	await expect(
		page.getByText(/review required/i).first(),
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
	const previewSave = page.getByRole("article").getByRole("button", { name: /^save$/i });
	await expect(previewSave).toBeVisible();
	await expect(page.getByText("Loading full description...")).toHaveCount(0, {
		timeout: 20_000,
	});
	await previewSave.focus();
	await page.keyboard.press("Enter");
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
	await expect(
		page.getByLabel(/keep verified search data available offline/i),
	).not.toBeChecked();
	await expect(
		page.getByText(/queries, workflow data, and full job details are not added/i),
	).toBeVisible();
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

	const list = page.getByRole("listbox", { name: /open jobs results/i });
	await list.focus();
	await page.keyboard.press("Home");
	await expect(list.getByRole("option").first()).toHaveAttribute(
		"data-focused",
		"true",
		{ timeout: 10_000 },
	);

	await page.keyboard.press("Enter");
	await expect(
		page.getByRole("article").getByRole("button", { name: /^save$/i }),
	).toBeVisible({
		timeout: 15_000,
	});
	await expect(
		page.getByRole("button", { name: /close job preview/i }),
	).toBeVisible({ timeout: 15_000 });
});

test("jobs board searches in a browser worker without server search requests", async ({ page }) => {
	test.setTimeout(90_000);
	let browserChunkRequests = 0;
	let serverSearchRequests = 0;
	await page.route("**/data/openopps-search/jobs/chunks/*.json", async (route) => {
		browserChunkRequests += 1;
		await route.continue();
	});
	await page.route("**/api/jobs/search**", async (route) => {
		serverSearchRequests += 1;
		await route.continue();
	});

	await page.goto("/");

	await searchForFirstJob(page, "platform");

	expect(browserChunkRequests).toBeGreaterThan(0);
	expect(serverSearchRequests).toBe(0);
});

test("jobs board removes all-indexed mode from the active filter chip", async ({
	page,
}) => {
	test.setTimeout(90_000);
	await page.goto("/");
	await searchForFirstJob(page, "platform");

	await page.getByRole("button", { name: /^All$/i }).click();
	const chip = page.getByRole("button", {
		name: /remove all indexed filter/i,
	});
	await expect(chip).toBeVisible({ timeout: 15_000 });
	// nuqs serializes booleans as true/false in the page URL; API still uses all=1.
	await expect(page).toHaveURL(/[?&]all=(true|1)(?:&|$)/, { timeout: 15_000 });
	await chip.click();

	await expect(page).not.toHaveURL(/[?&]all=(true|1)(?:&|$)/, { timeout: 15_000 });
	await expect(chip).toBeHidden();
	await expect(page.getByRole("button", { name: /^All$/i })).toHaveAttribute(
		"aria-pressed",
		"false",
	);
});
