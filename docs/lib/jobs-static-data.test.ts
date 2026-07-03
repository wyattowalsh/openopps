import fs from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
	canonicalJobUrl,
	clearStaticJobDataCachesForTests,
	formatJobDetailTitle,
	getJobSitemapCount,
	getJobSitemapUrls,
	getIndexableJobDetailIds,
	getStaticJobDetail,
	getStaticJobDetailIds,
	getStaticSearchManifest,
	isIndexableJobDetail,
	jobDetailDescriptionText,
	jobPostingJsonLd,
	jobPostingJsonLdEnabled,
	serializeJsonLdScript,
	safeJobExternalUrl,
	shouldEmitJobPostingJsonLd,
	shouldNoIndexDeployment,
} from "@/lib/jobs-static-data";

describe("jobs static data", () => {
	const originalEnv = { ...process.env };

	afterEach(() => {
		process.env = { ...originalEnv };
		vi.restoreAllMocks();
		clearStaticJobDataCachesForTests();
	});

	it("loads committed job detail ids and detail records", () => {
		const ids = getStaticJobDetailIds();
		const manifest = getStaticSearchManifest();
		expect(ids.length).toBe(manifest.detailShards?.count);
		expect(ids.length).toBeGreaterThan(10_000);

		const detail = getStaticJobDetail(ids[0]);
		expect(detail?.id).toBe(ids[0]);
		expect(detail?.status).toBeDefined();
		expect(formatJobDetailTitle(detail!)).toContain(
			detail?.title?.trim() || "Untitled role",
		);
		expect(canonicalJobUrl(ids[0])).toContain(encodeURIComponent(ids[0]));
	});

	it("encodes source-scoped job ids in static job URLs", () => {
		const jobId = "source:provider:role-1";

		expect(canonicalJobUrl(jobId)).toMatch(
			/\/jobs\/source%3Aprovider%3Arole-1$/,
		);
	});

	it("publishes only qualified job details in job sitemaps", () => {
		const manifest = getStaticSearchManifest();
		const indexableIds = getIndexableJobDetailIds();
		const expectedCount = manifest.detailShards?.indexableCount ?? 0;
		expect(indexableIds).toHaveLength(expectedCount);
		expect(getJobSitemapCount()).toBe(
			Math.ceil(expectedCount / 45000),
		);
		if (expectedCount === 0) {
			expect(getJobSitemapUrls(0)).toHaveLength(0);
		} else {
			expect(getJobSitemapUrls(0)).toHaveLength(
				Math.min(expectedCount, 45000),
			);
		}
	});

	it("uses precomputed indexable ids for modern snapshots without payload snapshots", () => {
		const payloads = new Map([
			[
				"manifest.json",
				JSON.stringify({
					version: 5,
					snapshotAt: "2026-01-01T00:00:00Z",
					source: {
						tables: ["board_providers", "boards", "jobs", "job_versions"],
					},
					detailShards: {
						count: 2,
						indexableCount: 2,
					},
				}),
			],
			[
				"jobs-indexable-ids.json",
				JSON.stringify({
					version: 5,
					count: 2,
					ids: ["job-1", "job-2"],
				}),
			],
		]);
		const payloadFor = (file: unknown) =>
			payloads.get(String(file).replace(/\\/g, "/").split("/").pop() ?? "");
		vi.spyOn(fs, "existsSync").mockImplementation((file) =>
			Boolean(payloadFor(file)),
		);
		vi.spyOn(fs, "readFileSync").mockImplementation(((file: unknown) => {
			const payload = payloadFor(file);
			if (payload) {
				return payload;
			}
			throw Object.assign(new Error(`Missing fixture file ${String(file)}`), {
				code: "ENOENT",
			});
		}) as typeof fs.readFileSync);

		clearStaticJobDataCachesForTests();

		expect(getStaticSearchManifest().source.tables).not.toContain(
			"job_payload_snapshots",
		);
		expect(getIndexableJobDetailIds()).toEqual(["job-1", "job-2"]);
		expect(getJobSitemapCount()).toBe(1);
	});

	it("keeps JobPosting JSON-LD behind data quality and kill-switch gates", () => {
		const detail = getStaticJobDetail(getStaticJobDetailIds()[0]);
		expect(detail).toBeTruthy();
		const detailIsIndexable = isIndexableJobDetail(detail!);
		delete process.env.OPENOPPS_JOBPOSTING_STRUCTURED_DATA;
		delete process.env.NEXT_PUBLIC_OPENOPPS_JOBPOSTING_STRUCTURED_DATA;
		expect(jobPostingJsonLdEnabled()).toBe(false);
		expect(shouldEmitJobPostingJsonLd(detail!)).toBe(false);
		expect(jobPostingJsonLd(detail!)).toBeNull();

		process.env.OPENOPPS_JOBPOSTING_STRUCTURED_DATA = "1";
		expect(jobPostingJsonLdEnabled()).toBe(true);
		expect(shouldEmitJobPostingJsonLd(detail!)).toBe(detailIsIndexable);

		const completeDetail = {
			id: "source:provider:job-1",
			status: "open",
			title: "Platform Engineer",
			company: "Acme Corp",
			description: "Build reliable services for production users.",
			postingUrl: "https://example.com/jobs/1",
			postedAt: "2026-06-01T00:00:00.000Z",
		};
		expect(isIndexableJobDetail(completeDetail)).toBe(true);
		expect(shouldEmitJobPostingJsonLd(completeDetail)).toBe(true);
		expect(jobPostingJsonLd(completeDetail)).toMatchObject({
			"@type": "JobPosting",
			title: "Platform Engineer",
			url: "https://example.com/jobs/1",
		});
		expect(isIndexableJobDetail({ ...completeDetail, status: "" })).toBe(true);
		expect(
			isIndexableJobDetail({ ...completeDetail, status: "closed" }),
		).toBe(false);
	});

	it("decodes HTML entities when deriving plain job descriptions", () => {
		expect(
			jobDetailDescriptionText({
				id: "source:provider:job-1",
				description:
					"Latency &amp;lt;60 ms &amp;amp; memory &amp;gt;1GB. &amp;lt;strong&amp;gt;Keep&amp;lt;/strong&amp;gt;",
				descriptionHtml: "<p>Ignored fallback</p>",
			}),
		).toBe("Latency <60 ms & memory >1GB. Keep");
		expect(
			jobDetailDescriptionText({
				id: "source:provider:job-2",
				descriptionHtml:
					"&amp;lt;p&amp;gt;Build&nbsp;R&amp;amp;D tools with &amp;#39;care&amp;#39;.&amp;lt;/p&amp;gt;",
			}),
		).toBe("Build R&D tools with 'care'.");
		expect(
			jobDetailDescriptionText({
				id: "source:provider:job-3",
				description:
					'Build. <span data-sheets-value="{&quot;2&quot;:&quot;Use <insert> &gt;95&quot;}" data-sheets-userformat="{&quot;2&quot;:769}">visible</span>',
			}),
		).toBe("Build. visible");
	});

	it("returns null for unknown or malformed job ids instead of throwing", () => {
		expect(getStaticJobDetail("definitely-not-a-real-job-id-%ZZ")).toBeNull();
		expect(getStaticJobDetail("missing-shard-job-id-00000000")).toBeNull();
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
	});

	it("serializes JSON-LD without script breakouts", () => {
		const malicious = {
			"@context": "https://schema.org",
			"@type": "JobPosting",
			title: '</script><script>alert(1)</script>',
			description: "Safe body",
		};
		const serialized = serializeJsonLdScript(malicious);
		expect(serialized).not.toContain("</script>");
		expect(serialized).toContain("\\u003c/script\\u003e");
	});

	it("detects preview/noindex deployment mode", () => {
		delete process.env.OPENOPPS_NOINDEX;
		delete process.env.VERCEL_ENV;
		expect(shouldNoIndexDeployment()).toBe(false);
		process.env.VERCEL_ENV = "preview";
		expect(shouldNoIndexDeployment()).toBe(true);
		process.env.VERCEL_ENV = "production";
		process.env.OPENOPPS_NOINDEX = "1";
		expect(shouldNoIndexDeployment()).toBe(true);
	});
});
