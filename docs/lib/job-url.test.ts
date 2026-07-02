import { describe, expect, it } from "vitest";

import { cleanText, safeJobExternalUrl } from "@/lib/job-url";

describe("job-url", () => {
	it("normalizes whitespace in cleanText", () => {
		expect(cleanText("  hello   world  ")).toBe("hello world");
		expect(cleanText(null)).toBe("");
		expect(cleanText(42)).toBe("");
	});

	it("only accepts HTTP(S) external job urls", () => {
		expect(safeJobExternalUrl("https://example.com/jobs/1")).toBe(
			"https://example.com/jobs/1",
		);
		expect(safeJobExternalUrl("http://example.com/jobs/1")).toBe(
			"http://example.com/jobs/1",
		);
		expect(safeJobExternalUrl("/jobs/1")).toBeNull();
		expect(safeJobExternalUrl("javascript:alert(1)")).toBeNull();
		expect(safeJobExternalUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
	});

	it("rejects credential-bearing urls", () => {
		expect(safeJobExternalUrl("https://user:pass@example.com/jobs/1")).toBeNull();
		expect(safeJobExternalUrl("https://user@example.com/jobs/1")).toBeNull();
		expect(safeJobExternalUrl("https://:pass@example.com/jobs/1")).toBeNull();
	});
});
