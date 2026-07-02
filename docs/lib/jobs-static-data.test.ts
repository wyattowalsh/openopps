import { afterEach, describe, expect, it } from "vitest";

import {
	canonicalJobUrl,
	formatJobDetailTitle,
	getJobSitemapCount,
	getJobSitemapUrls,
	getIndexableJobDetailIds,
	getStaticJobDetail,
	getStaticJobDetailIds,
	getStaticSearchManifest,
	isIndexableJobDetail,
	jobPostingJsonLd,
	jobPostingJsonLdEnabled,
	safeJobExternalUrl,
	shouldEmitJobPostingJsonLd,
	shouldNoIndexDeployment,
} from "@/lib/jobs-static-data";

describe("jobs static data", () => {
	const originalEnv = { ...process.env };

	afterEach(() => {
		process.env = { ...originalEnv };
	});

	it("loads committed job detail ids and detail records", () => {
		const ids = getStaticJobDetailIds();
		const manifest = getStaticSearchManifest();
		expect(ids.length).toBe(manifest.detailShards?.count);
		expect(ids.length).toBeGreaterThan(10_000);

		const detail = getStaticJobDetail(ids[0]);
		expect(detail?.id).toBe(ids[0]);
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

	it("does not publish thin committed job details in job sitemaps", () => {
		expect(getStaticSearchManifest().source.tables).not.toContain(
			"job_payload_snapshots",
		);
		expect(getIndexableJobDetailIds()).toHaveLength(0);
		expect(getJobSitemapCount()).toBe(0);
		const urls = getJobSitemapUrls(0);
		expect(urls).toHaveLength(0);
	});

	it("keeps JobPosting JSON-LD behind data quality and kill-switch gates", () => {
		const detail = getStaticJobDetail(getStaticJobDetailIds()[0]);
		expect(detail).toBeTruthy();
		delete process.env.OPENOPPS_JOBPOSTING_STRUCTURED_DATA;
		delete process.env.NEXT_PUBLIC_OPENOPPS_JOBPOSTING_STRUCTURED_DATA;
		expect(jobPostingJsonLdEnabled()).toBe(false);
		expect(isIndexableJobDetail(detail!)).toBe(false);
		expect(shouldEmitJobPostingJsonLd(detail!)).toBe(false);
		expect(jobPostingJsonLd(detail!)).toBeNull();

		process.env.OPENOPPS_JOBPOSTING_STRUCTURED_DATA = "1";
		expect(jobPostingJsonLdEnabled()).toBe(true);
		expect(shouldEmitJobPostingJsonLd(detail!)).toBe(false);

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
