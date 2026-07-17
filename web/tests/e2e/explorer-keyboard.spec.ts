import { expect, test } from "@playwright/test";

test("explorer row inspector supports keyboard navigation and activation", async ({
	page,
}) => {
	test.setTimeout(90_000);
	await page.goto("/explorer");
	await page.getByRole("button", { name: /inspect rows/i }).click();
	await page.getByRole("button", { name: /show boards/i }).click();

	const list = page.getByRole("list", { name: /boards results/i });
	// Wait for explorer store/chunks to hydrate before asserting keyboard focus.
	await expect(list.getByRole("listitem").first()).toBeVisible({
		timeout: 60_000,
	});
	await expect(list.getByRole("link", { name: /open board/i }).first()).toBeVisible({
		timeout: 15_000,
	});

	await list.focus();
	await page.keyboard.press("ArrowDown");
	await expect(list.getByRole("listitem").first()).toHaveAttribute(
		"data-focused",
		"true",
		{ timeout: 10_000 },
	);

	const popupPromise = page.waitForEvent("popup", { timeout: 15_000 });
	await page.keyboard.press("Enter");
	const popup = await popupPromise;
	expect(popup.url()).not.toBe("");
	await popup.close();

	await page.getByRole("button", { name: /dashboard/i }).click();
	await expect(page.getByRole("heading", { name: /generated index rows/i })).toBeHidden();
});
