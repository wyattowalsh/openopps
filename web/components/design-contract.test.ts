import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("web design contract", () => {
	it("does not use uppercase letter-spacing as component label hierarchy", () => {
		const offenders = componentFiles(join(process.cwd(), "components")).filter(
			(file) =>
				!file.endsWith("design-contract.test.ts") &&
				readFileSync(file, "utf8").includes("uppercase tracking-"),
		);

		expect(offenders).toEqual([]);
	});

	it("keeps workbench empty/loading/error surface classes in global CSS", () => {
		const css = readFileSync(join(process.cwd(), "app/global.css"), "utf8");
		for (const token of [
			".opps-empty-state",
			".opps-loading",
			".opps-error-banner",
			".opps-ledger-shell",
			".opps-toolbar",
			".opps-metric",
		]) {
			expect(css.includes(token), `missing ${token}`).toBe(true);
		}
	});
});

function componentFiles(root: string): string[] {
	return readdirSync(root).flatMap((entry) => {
		const path = join(root, entry);
		const stat = statSync(path);
		if (stat.isDirectory()) {
			return componentFiles(path);
		}
		return /\.(tsx|ts)$/.test(entry) ? [path] : [];
	});
}
