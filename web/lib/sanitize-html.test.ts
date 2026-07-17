// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { sanitizeJobDescriptionHtml } from "@/lib/sanitize-html";

describe("sanitize-html", () => {
	it("strips script and event-handler vectors", () => {
		expect(sanitizeJobDescriptionHtml('<img src=x onerror="alert(1)">')).not.toContain(
			"onerror",
		);
		expect(sanitizeJobDescriptionHtml("<svg><script>alert(1)</script></svg>")).not.toContain(
			"<script",
		);
	});

	it("removes javascript: links", () => {
		const sanitized = sanitizeJobDescriptionHtml(
			'<a href="javascript:alert(1)">click</a>',
		);
		expect(sanitized).not.toContain("javascript:");
	});

	it("removes relative, protocol-relative, and credential-bearing links", () => {
		const sanitized = sanitizeJobDescriptionHtml(
			[
				'<a href="/apply">relative</a>',
				'<a href="//example.com/apply">protocol relative</a>',
				'<a href="https://user:pass@example.com/apply">credentials</a>',
			].join(""),
		);

		expect(sanitized).not.toContain('href="/apply"');
		expect(sanitized).not.toContain('href="//example.com/apply"');
		expect(sanitized).not.toContain("user:pass");
	});

	it("keeps safe links with noopener attributes", () => {
		const sanitized = sanitizeJobDescriptionHtml(
			'<a href="https://example.com/jobs/1">Apply</a>',
		);
		expect(sanitized).toContain('href="https://example.com/jobs/1"');
		expect(sanitized).toContain('rel="noopener noreferrer"');
		expect(sanitized).toContain('target="_blank"');
	});

	it("neutralizes known mXSS-style attribute breakout attempts", () => {
		const sanitized = sanitizeJobDescriptionHtml(
			'<img src="x"><img src=x onerror=alert(1)//',
		);
		expect(sanitized.toLowerCase()).not.toContain("onerror");
		expect(sanitized).not.toContain("<script");
	});
});
