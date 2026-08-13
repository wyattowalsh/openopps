import { describe, expect, it, vi } from "vitest";

import type {
	SearchManifest,
	SnapshotChannelPointer,
	SnapshotFileEntry,
	SnapshotReleaseManifest,
} from "@/components/openopps-search/search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	detailBucket,
} from "@/components/openopps-search/search-utils";

import { OpenOppsSnapshotClient } from "./openopps-snapshot-client";

const origin = "https://data.openopps.test/";
const snapshotAt = "2026-08-12T12:00:00.000000Z";

describe("OpenOppsSnapshotClient v7", () => {
	it("pins the first resolved release when the mutable channel later changes", async () => {
		const first = await releaseFixture({
			"search-manifest.json": searchManifest({
				detailShards: {
					root: "/data/openopps-search/jobs-details",
					indexableIdIndexPath:
						"/data/openopps-search/jobs-indexable-ids.json",
					bucketCount: 1024,
					count: 0,
				},
			}),
			"jobs-indexable-ids.json": { version: 6, count: 1, ids: ["job-a"] },
		});
		const second = await releaseFixture({
			"search-manifest.json": searchManifest({
				detailShards: {
					root: "/data/openopps-search/jobs-details",
					indexableIdIndexPath:
						"/data/openopps-search/jobs-indexable-ids.json",
					bucketCount: 1024,
					count: 0,
				},
			}),
			"jobs-indexable-ids.json": { version: 6, count: 1, ids: ["job-b"] },
		});
		let channelReads = 0;
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith("/channels/production.json")) {
				channelReads += 1;
				return jsonResponse(
					channelReads === 1 ? first.pointer : second.pointer,
				);
			}
			return fixtureResponse(url, first);
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getSearchManifest()).resolves.toMatchObject({ version: 6 });
		await expect(client.getIndexableJobIds()).resolves.toEqual(["job-a"]);
		await expect(client.releaseId()).resolves.toBe(first.manifest.releaseId);
		expect(channelReads).toBe(1);
		expect(fetchMock).not.toHaveBeenCalledWith(
			expect.objectContaining({ href: expect.stringContaining(second.manifest.releaseId) }),
			expect.anything(),
		);
	});

	it("opens a trusted pinned release without re-reading the mutable channel", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const fetchMock = fixtureFetch(fixture);
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			pinnedReleaseId: fixture.manifest.releaseId,
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getSearchManifest()).resolves.toMatchObject({ version: 6 });
		expect(fetchMock).not.toHaveBeenCalledWith(
			new URL("channels/production.json", origin),
			expect.anything(),
		);
		expect(fetchMock).toHaveBeenCalledWith(
			new URL(`releases/${fixture.manifest.releaseId}/manifest.json`, origin),
			expect.objectContaining({ cache: "force-cache" }),
		);
	});

	it("reads a pinned release only from its explicitly-owned offline cache", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const networkFetch = vi.fn(async () => {
			throw new Error("network must not be used for a complete offline release");
		});
		const offlineResponseReader = vi.fn(async (url: URL) => {
			if (url.pathname.includes("/channels/")) return null;
			const response = fixtureResponse(url.href, fixture);
			return response.status === 404 ? null : response;
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			pinnedReleaseId: fixture.manifest.releaseId,
			offlineResponseReader,
			fetchImpl: networkFetch as unknown as typeof fetch,
		});

		await expect(client.getSearchManifest()).resolves.toMatchObject({ version: 6 });
		expect(offlineResponseReader).toHaveBeenCalledWith(
			new URL(`releases/${fixture.manifest.releaseId}/manifest.json`, origin),
		);
		expect(networkFetch).not.toHaveBeenCalled();
	});

	it("falls back to the last verified pinned release only on channel network failure", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const networkFetch = vi.fn(async () => {
			throw new TypeError("offline");
		});
		const offlineResponseReader = vi.fn(async (url: URL) => {
			if (url.pathname.includes("/channels/")) return null;
			const response = fixtureResponse(url.href, fixture);
			return response.status === 404 ? null : response;
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			offlineFallbackReleaseId: fixture.manifest.releaseId,
			offlineResponseReader,
			fetchImpl: networkFetch as unknown as typeof fetch,
		});

		await expect(client.getSearchManifest()).resolves.toMatchObject({ version: 6 });
		await expect(client.releaseId()).resolves.toBe(fixture.manifest.releaseId);
		expect(networkFetch).toHaveBeenCalledTimes(1);
	});

	it("does not hide an invalid online channel selection behind an offline fallback", async () => {
		const cached = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const selected = await releaseFixture({
			"search-manifest.json": {
				...searchManifest(),
				kaggleDatasetId: "selected/release",
			},
		});
		const substituted = await releaseFixture({
			"search-manifest.json": {
				...searchManifest(),
				kaggleDatasetId: "substituted/release",
			},
		});
		const networkFetch = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith("/channels/production.json")) {
				return jsonResponse(selected.pointer);
			}
			if (url.endsWith(`/${selected.pointer.manifestPath}`)) {
				return jsonResponse(substituted.manifest);
			}
			return new Response(null, { status: 404 });
		});
		const offlineResponseReader = vi.fn(async (url: URL) => {
			if (url.pathname.includes("/channels/")) return null;
			const response = fixtureResponse(url.href, cached);
			return response.status === 404 ? null : response;
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			offlineFallbackReleaseId: cached.manifest.releaseId,
			offlineResponseReader,
			fetchImpl: networkFetch as typeof fetch,
		});

		await expect(client.getSearchManifest()).rejects.toMatchObject({
			code: "invalid_manifest",
		});
		expect(networkFetch).toHaveBeenCalledTimes(2);
	});

	it("does not treat an HTTP channel response as an offline network outage", async () => {
		const cached = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const offlineResponseReader = vi.fn(async (url: URL) => {
			if (url.pathname.includes("/channels/")) return null;
			const response = fixtureResponse(url.href, cached);
			return response.status === 404 ? null : response;
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			offlineFallbackReleaseId: cached.manifest.releaseId,
			offlineResponseReader,
			fetchImpl: vi.fn(async () => new Response(null, { status: 404 })) as typeof fetch,
		});

		await expect(client.releaseId()).rejects.toMatchObject({
			code: "fetch_failed",
			message: expect.stringMatching(/HTTP 404/),
		});
		expect(offlineResponseReader).not.toHaveBeenCalledWith(
			new URL(`releases/${cached.manifest.releaseId}/manifest.json`, origin),
		);
	});

	it("rejects an invalid or substituted pinned release identity", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		expect(
			() =>
				new OpenOppsSnapshotClient({
					baseUrl: origin,
					pinnedReleaseId: "not-a-digest",
				}),
		).toThrow(/lowercase SHA-256/);
		const otherReleaseId = "f".repeat(64);
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith(`/releases/${otherReleaseId}/manifest.json`)) {
				return jsonResponse(fixture.manifest);
			}
			return new Response(null, { status: 404 });
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			pinnedReleaseId: otherReleaseId,
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.releaseId()).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/pinned release ID/),
		});
	});

	it("rejects a channel whose selected manifest belongs to another release", async () => {
		const selected = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const substituted = await releaseFixture({
			"search-manifest.json": {
				...searchManifest(),
				kaggleDatasetId: "substituted/release",
			},
		});
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith("/channels/production.json")) {
				return jsonResponse(selected.pointer);
			}
			if (url.endsWith(`/${selected.pointer.manifestPath}`)) {
				return jsonResponse(substituted.manifest);
			}
			return new Response(null, { status: 404 });
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_manifest",
		});
	});

	it("rejects unsafe asset paths even when the pointer and root digest agree", async () => {
		const fixture = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ pathOverride: "jobs/../search-manifest.json" },
		);
		const client = clientForFixture(fixture);

		await expect(client.getSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_manifest",
			message: expect.stringMatching(/invalid file entry|unsafe/i),
		});
	});

	it("rejects non-portable release paths before case-collision handling", async () => {
		const fixture = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ pathOverride: "données/search-manifest.json" },
		);

		await expect(clientForFixture(fixture).getSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_manifest",
			message: expect.stringMatching(/invalid file entry|unsafe/i),
		});
	});

	it("rejects unsafe provenance paths even when their canonical digest agrees", async () => {
		const unsafeSource = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ sourcePathOverride: "../private.sqlite" },
		);
		const unsafeEntrypoint = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ generatorEntrypointOverride: "https://example.test/generator.py" },
		);

		await expect(clientForFixture(unsafeSource).getSearchManifest()).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/manifest is invalid/i),
		});
		await expect(
			clientForFixture(unsafeEntrypoint).getSearchManifest(),
		).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/manifest is invalid/i),
		});
	});

	it("rejects incoherent channel snapshot age metadata", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		fixture.pointer.snapshotAgeSeconds = 1;

		await expect(clientForFixture(fixture).getSearchManifest()).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/snapshotAgeSeconds/i),
		});
	});

	it("rejects manifests beyond the file-count and per-file byte budgets", async () => {
		const tooManyFiles = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ extraFileCount: 18_000 },
		);
		const oversizedFile = await releaseFixture(
			{ "search-manifest.json": searchManifest() },
			{ entryBytesOverride: 24 * 1024 * 1024 },
		);

		await expect(
			clientForFixture(tooManyFiles).getSearchManifest(),
		).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/18,?000 file/i),
		});
		await expect(
			clientForFixture(oversizedFile).getSearchManifest(),
		).rejects.toMatchObject({
			code: "invalid_manifest",
			message: expect.stringMatching(/smaller than 25165824 bytes/i),
		});
	});

	it("fetches remote details only from the pinned release and verifies bytes", async () => {
		const jobId = "source:provider:job-a";
		const bucket = detailBucket(jobId);
		const manifest = searchManifest({
			detailShards: {
				root: "/data/openopps-search/jobs-details",
				format: "bucket-map",
				idIndexPath: "/data/openopps-search/jobs-detail-ids.json",
				indexableIdIndexPath:
					"/data/openopps-search/jobs-indexable-ids.json",
				bucketCount: 1024,
				count: 1,
			},
		});
		const fixture = await releaseFixture({
			"search-manifest.json": manifest,
			[`jobs-details/${bucket}.json`]: {
				[jobId]: { id: jobId, title: "Pinned platform engineer" },
			},
		});
		const legacyReader = vi.fn(async () => {
			throw new Error("filesystem must not be used for a remote v7 release");
		});
		const fetchMock = fixtureFetch(fixture);
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			legacyFileReader: legacyReader,
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getJobDetail(jobId)).resolves.toMatchObject({
			id: jobId,
			title: "Pinned platform engineer",
		});
		expect(legacyReader).not.toHaveBeenCalled();
		expect(fetchMock).toHaveBeenCalledWith(
			new URL(
				`releases/${fixture.manifest.releaseId}/jobs-details/${bucket}.json`,
				origin,
			),
			expect.objectContaining({ cache: "force-cache" }),
		);
	});

	it("fails closed when immutable asset bytes do not match the manifest", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith("/channels/production.json")) {
				return jsonResponse(fixture.pointer);
			}
			if (url.endsWith(`/${fixture.pointer.manifestPath}`)) {
				return jsonResponse(fixture.manifest);
			}
			return jsonResponse({ version: 6, tampered: true });
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_chunk",
			message: expect.stringMatching(/byte size|SHA-256|byte budget/),
		});
	});

	it("rejects an oversized immutable response from Content-Length before reading it", async () => {
		const fixture = await releaseFixture({
			"search-manifest.json": searchManifest(),
		});
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.endsWith("/channels/production.json")) {
				return jsonResponse(fixture.pointer);
			}
			if (url.endsWith(`/${fixture.pointer.manifestPath}`)) {
				return jsonResponse(fixture.manifest);
			}
			return new Response("{}", {
				headers: { "Content-Length": String(24 * 1024 * 1024) },
			});
		});
		const client = new OpenOppsSnapshotClient({
			baseUrl: origin,
			channel: "production",
			fetchImpl: fetchMock as typeof fetch,
		});

		await expect(client.getSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_chunk",
			message: expect.stringMatching(/response exceeds.*byte budget/i),
		});
	});
});

type Fixture = {
	pointer: SnapshotChannelPointer;
	manifest: SnapshotReleaseManifest;
	assets: Map<string, string>;
};

async function releaseFixture(
	payloads: Record<string, unknown>,
	options: {
		pathOverride?: string;
		entryBytesOverride?: number;
		extraFileCount?: number;
		sourcePathOverride?: string;
		generatorEntrypointOverride?: string;
	} = {},
): Promise<Fixture> {
	const assets = new Map<string, string>();
	const files: SnapshotFileEntry[] = [];
	for (const [sourcePath, payload] of Object.entries(payloads).sort()) {
		const raw = JSON.stringify(payload);
		const manifestPath = options.pathOverride ?? sourcePath;
		assets.set(sourcePath, raw);
		files.push({
			path: manifestPath,
			bytes:
				options.entryBytesOverride ??
				new TextEncoder().encode(raw).byteLength,
			mediaType: "application/json",
			sha256: await sha256(raw),
			role: sourcePath === "search-manifest.json" ? "search-manifest" : roleFor(sourcePath),
			count: semanticCount(payload),
		});
	}
	const emptyDigest = await sha256("{}");
	for (let index = 0; index < (options.extraFileCount ?? 0); index += 1) {
		files.push({
			path: `extra/${String(index).padStart(5, "0")}.json`,
			bytes: 2,
			mediaType: "application/json",
			sha256: emptyDigest,
			role: "artifact",
			count: 0,
		});
	}
	const body = {
		schemaVersion: 7 as const,
		snapshotAt,
		source: {
			kind: "sqlite" as const,
			path: options.sourcePathOverride ?? "kaggle/openoppsdb.sqlite",
			bytes: 100,
			sha256: "1".repeat(64),
		},
		generator: {
			name: "openopps-docs-search-index",
			entrypoint:
				options.generatorEntrypointOverride ??
				"scripts/generate_docs_search_index.py",
			components: [
				{ path: "scripts/generate_docs_search_index.py", sha256: "2".repeat(64) },
			],
			payloadSchemaVersion: 6,
		},
		fileCount: files.length,
		totalBytes: files.reduce((total, file) => total + file.bytes, 0),
		files,
	};
	const releaseId = await sha256(canonicalJson(body));
	const manifest: SnapshotReleaseManifest = {
		...body,
		releaseId,
		rootDigest: { algorithm: "sha256", value: releaseId },
	};
	return {
		manifest,
		assets,
		pointer: {
			schemaVersion: 2,
			channel: "production",
			releaseId,
			rootDigest: { algorithm: "sha256", value: releaseId },
			snapshotAt,
			manifestPath: `releases/${releaseId}/manifest.json`,
			priorReleaseId: null,
			degradedReason: null,
			promotedAt: snapshotAt,
			snapshotAgeSeconds: 0,
		},
	};
}

function searchManifest(overrides: Partial<SearchManifest> = {}): SearchManifest {
	return {
		version: 6,
		snapshotAt,
		source: { database: "kaggle/openoppsdb.sqlite", tables: [] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { columns: EXPECTED_JOB_COLUMNS, count: 0 },
			boards: { columns: EXPECTED_BOARD_COLUMNS, count: 0 },
			providers: { columns: EXPECTED_PROVIDER_COLUMNS, count: 0 },
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: [],
			supportLevels: [],
			routeStatuses: [],
			workplaces: [],
			employmentTypes: [],
		},
		...overrides,
	};
}

function clientForFixture(fixture: Fixture) {
	return new OpenOppsSnapshotClient({
		baseUrl: origin,
		channel: "production",
		fetchImpl: fixtureFetch(fixture) as typeof fetch,
	});
}

function fixtureFetch(fixture: Fixture) {
	return vi.fn(async (input: RequestInfo | URL) =>
		fixtureResponse(String(input), fixture),
	);
}

function fixtureResponse(url: string, fixture: Fixture) {
	if (url.endsWith("/channels/production.json")) {
		return jsonResponse(fixture.pointer);
	}
	if (url.endsWith(`/${fixture.pointer.manifestPath}`)) {
		return jsonResponse(fixture.manifest);
	}
	const releasePrefix = `${origin}releases/${fixture.manifest.releaseId}/`;
	if (url.startsWith(releasePrefix)) {
		const raw = fixture.assets.get(url.slice(releasePrefix.length));
		return raw === undefined
			? new Response(null, { status: 404 })
			: new Response(raw, {
					headers: { "Content-Type": "application/json" },
				});
	}
	return new Response(null, { status: 404 });
}

function jsonResponse(value: unknown) {
	return new Response(JSON.stringify(value), {
		headers: { "Content-Type": "application/json" },
	});
}

function roleFor(path: string) {
	if (path.startsWith("jobs-details/")) return "job-details";
	if (path === "jobs-indexable-ids.json") return "job-indexable-ids";
	return "artifact";
}

function semanticCount(value: unknown) {
	if (value && typeof value === "object") {
		const record = value as Record<string, unknown>;
		if (Array.isArray(record.rows)) return record.rows.length;
		if (Array.isArray(record.ids)) return record.ids.length;
		if (typeof record.count === "number") return record.count;
		return Object.keys(record).length;
	}
	if (Array.isArray(value)) return value.length;
	return 1;
}

function canonicalJson(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
	return `{${Object.entries(value as Record<string, unknown>)
		.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
		.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
		.join(",")}}`;
}

async function sha256(value: string) {
	const bytes = new TextEncoder().encode(value);
	const digest = new Uint8Array(
		await crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer),
	);
	return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
