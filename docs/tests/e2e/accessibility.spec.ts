import AxeBuilder from "@axe-core/playwright";
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

test("jobs workbench and local settings pass baseline accessibility checks", async ({
	page,
}) => {
	await page.goto("/");
	await expect(
		page.getByRole("button", { name: /save current search/i }),
	).toBeVisible();
	await waitForFirstJob(page);

	const workbenchScan = await new AxeBuilder({ page })
		.include("main")
		.exclude('[role="listbox"][aria-label="Open jobs results"]')
		.disableRules(["color-contrast"])
		.analyze();
	expect(workbenchScan.violations).toEqual([]);

	await page.getByRole("button", { name: /open app settings/i }).click();
	await expect(page.getByRole("dialog", { name: /app settings/i })).toBeVisible();
	const settingsScan = await new AxeBuilder({ page })
		.include('[role="dialog"]')
		.disableRules(["color-contrast"])
		.analyze();
	expect(settingsScan.violations).toEqual([]);
});

test("mobile preview sheet keeps dialog semantics", async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/");

	const firstJob = await waitForFirstJob(page);
	await firstJob.click();

	const dialog = page.getByRole("dialog", { name: /job preview/i });
	await expect(dialog).toBeVisible();
	await expect(page.getByRole("button", { name: /close job preview/i })).toBeVisible();

	const scan = await new AxeBuilder({ page })
		.include('[role="dialog"]')
		.disableRules(["color-contrast"])
		.analyze();
	expect(scan.violations).toEqual([]);
});
