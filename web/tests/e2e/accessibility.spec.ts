import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// Axe scans are heavy; keep a11y cases serial within this file to reduce flake.
test.describe.configure({ mode: "serial" });

async function waitForFirstJob(page: Page) {
	const firstJob = page
		.getByRole("listbox", { name: /open jobs results/i })
		.getByRole("option")
		.first();
	await expect(firstJob).toBeVisible({ timeout: 30_000 });
	return firstJob;
}

async function searchForFirstJob(page: Page) {
	const search = page.getByLabel("Search jobs");
	await expect(search).toBeVisible({ timeout: 30_000 });
	await waitForFirstJob(page);
	await search.fill("platform");
	await expect(search).toHaveValue("platform");
	await expect(page).toHaveURL(
		(url) => url.searchParams.get("q") === "platform",
		{ timeout: 15_000 },
	);
	return waitForFirstJob(page);
}

async function expectNoAxeViolations(
	page: Page,
	options: { include: string; exclude?: string },
) {
	const builder = new AxeBuilder({ page }).include(options.include);
	if (options.exclude) {
		builder.exclude(options.exclude);
	}
	const scan = await builder.analyze();
	expect(scan.violations).toEqual([]);
}

function escapeRegExp(value: string) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function expectOptionNameMatchesVisibleText(page: Page) {
	const firstJob = page
		.getByRole("listbox", { name: /open jobs results/i })
		.getByRole("option")
		.first();
	await expect(firstJob).not.toHaveAttribute("aria-label");
	const visibleTitle = (await firstJob.locator("span").first().innerText()).trim();
	expect(visibleTitle.length).toBeGreaterThan(0);
	await expect(firstJob).toHaveAccessibleName(
		new RegExp(escapeRegExp(visibleTitle)),
	);
}

test("jobs workbench and local settings pass baseline accessibility checks", async ({
	page,
}) => {
	// Axe over the full main surface is slower on cold Next starts.
	test.setTimeout(120_000);
	await page.goto("/");
	await expect(
		page.getByRole("button", { name: /save current search/i }),
	).toBeVisible();
	await searchForFirstJob(page);
	await expectOptionNameMatchesVisibleText(page);

	// Exclude the virtualized jobs listbox from full axe runs: option density and
	// focus management are covered by unit contracts and keyboard paths instead of
	// a flaky full-surface axe baseline on large option sets.
	await expectNoAxeViolations(page, {
		include: "main",
		exclude: '[role="listbox"][aria-label="Open jobs results"]',
	});

	await page.getByRole("button", { name: /open app settings/i }).click();
	await expect(page.getByRole("dialog", { name: /app settings/i })).toBeVisible();
	await expectNoAxeViolations(page, { include: '[role="dialog"]' });
});

test("mobile preview sheet keeps dialog semantics", async ({ page }) => {
	test.setTimeout(90_000);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/");

	const firstJob = await searchForFirstJob(page);
	await firstJob.click();
	await expect(page).toHaveURL((url) => url.searchParams.has("job"), {
		timeout: 15_000,
	});

	const dialog = page.getByRole("dialog", { name: /job preview/i });
	await expect(dialog).toBeVisible();
	await expect(page.getByRole("button", { name: /close job preview/i })).toBeVisible();

	await expectNoAxeViolations(page, { include: '[role="dialog"]' });
});

test("explorer index passes baseline accessibility checks", async ({ page }) => {
	await page.goto("/explorer");
	await expect(page.getByRole("main")).toBeVisible({ timeout: 30_000 });
	await expect(
		page.getByRole("heading", { name: /data pipeline dashboard/i }),
	).toBeVisible({ timeout: 30_000 });

	await expectNoAxeViolations(page, { include: "main" });
});

test("delete saved search uses an accessible confirmation dialog", async ({
	page,
}) => {
	await page.goto("/");
	await searchForFirstJob(page);
	const saveSearch = page.getByRole("button", { name: /save current search/i });
	await expect(saveSearch).toBeEnabled({ timeout: 15_000 });
	await saveSearch.click();
	const savedDetails = page.locator("details").filter({ hasText: "Saved searches" });
	await expect(savedDetails).toBeVisible({ timeout: 20_000 });
	await savedDetails.locator("summary").click();
	await expect(savedDetails).toHaveAttribute("open", "");

	const deleteButton = page.getByRole("button", { name: /^delete /i }).first();
	await expect(deleteButton).toBeVisible({ timeout: 20_000 });
	await deleteButton.click();

	const confirmDialog = page.getByRole("alertdialog", {
		name: /delete saved search/i,
	});
	await expect(confirmDialog).toBeVisible();
	await expectNoAxeViolations(page, { include: '[role="alertdialog"]' });

	await page.getByRole("button", { name: /^keep$/i }).click();
	await expect(confirmDialog).toBeHidden();
});
