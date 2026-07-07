import { expect, test } from "@playwright/test";

test("explorer row inspector supports keyboard navigation and activation", async ({
	page,
}) => {
	await page.goto("/explorer");
	await page.getByRole("button", { name: /inspect rows/i }).click();
	await page.getByRole("button", { name: /show boards/i }).click();

	const list = page.getByRole("list", { name: /boards results/i });
	await expect(list.getByRole("listitem").first()).toBeVisible({
		timeout: 30_000,
	});
	await expect(list.getByRole("link", { name: /open board/i }).first()).toBeVisible();

	await list.focus();
	await page.keyboard.press("ArrowDown");
	await expect(list.getByRole("listitem").first()).toHaveAttribute(
		"data-focused",
		"true",
	);

	const popupPromise = page.waitForEvent("popup");
	await page.keyboard.press("Enter");
	const popup = await popupPromise;
	expect(popup.url()).not.toBe("");
	await popup.close();

	await page.getByRole("button", { name: /dashboard/i }).click();
	await expect(page.getByRole("heading", { name: /generated index rows/i })).toBeHidden();
});
