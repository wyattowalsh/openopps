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
	const firstJob = await waitForFirstJob(page);

	await page.getByRole("button", { name: /save current search/i }).click();
	await page.getByText("Saved searches", { exact: true }).click();
	await expect(page.getByText(/new or changed/).first()).toBeVisible();

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
	await waitForFirstJob(page);

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
	await waitForFirstJob(page);

	const searchResponse = page.waitForResponse(
		(response) => response.url().includes("/api/jobs/search") && response.ok(),
		{ timeout: 30_000 },
	);
	await page.getByLabel("Search jobs").fill("platform");
	await searchResponse;

	expect(browserChunkRequests).toBe(0);
});
