import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("docs design contract", () => {
	it("does not use uppercase letter-spacing as component label hierarchy", () => {
		const offenders = componentFiles(join(process.cwd(), "components")).filter(
			(file) =>
				!file.endsWith("design-contract.test.ts") &&
				readFileSync(file, "utf8").includes("uppercase tracking-"),
		);

		expect(offenders).toEqual([]);
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
