import { describe, expect, it, vi } from "vitest";

import type { SnapshotFileEntry } from "@/components/openopps-search/search-types";
import type { SnapshotOfflineReleasePlan } from "@/lib/openopps-snapshot-client";
import {
	createJobsOfflineCacheReader,
	disableJobsOfflineCache,
	getJobsOfflineSnapshotConfiguration,
	isJobsOfflineOptedIn,
	JOBS_OFFLINE_CACHE_PREFIX,
	JOBS_OFFLINE_MAX_ENTRIES,
	JOBS_OFFLINE_OPT_IN_KEY,
	JOBS_OFFLINE_READY_KEY,
	prepareJobsOfflineCache,
	readJobsOfflineReady,
	setJobsOfflineOptIn,
	verifyJobsOfflineCache,
	verifyOrDiscardJobsOfflineCache,
} from "./jobs-offline-cache";

const origin = "https://data.openopps.test/";

describe("jobs offline cache", () => {
	it("is default-off and performs no cache or network work before opt-in", async () => {
		const harness = createHarness();
		const plan = releasePlan();

		expect(isJobsOfflineOptedIn(harness.storage)).toBe(false);
		expect(
			getJobsOfflineSnapshotConfiguration(origin, harness.dependencies),
		).toBeNull();
		await expect(
			prepareJobsOfflineCache(plan, { dependencies: harness.dependencies }),
		).rejects.toMatchObject({ code: "opt_out" });
		expect(harness.fetchImpl).not.toHaveBeenCalled();
		expect(await harness.cacheStorage.keys()).toEqual([]);
	});

	it("preflights exact 2x headroom, verifies every byte, and claims readiness last", async () => {
		const plan = releasePlan();
		const totalBytes = projectedBytes(plan);
		const progress: Array<{ completedEntries: number; totalEntries: number }> = [];
		const harness = createHarness(plan, {
			quota: totalBytes * 2 + 7,
			usage: 7,
		});
		await harness.cacheStorage.open("unrelated-app-cache");
		setJobsOfflineOptIn(true, harness.storage);

		const ready = await prepareJobsOfflineCache(plan, {
			dependencies: harness.dependencies,
			onProgress: (value) => progress.push(value),
		});

		expect(ready).toMatchObject({
			releaseId: plan.releaseId,
			entryCount: 3,
			totalBytes,
		});
		expect(readJobsOfflineReady(harness.storage)).toEqual(ready);
		expect(await harness.cacheStorage.keys()).toEqual([
			"unrelated-app-cache",
			ready.cacheName,
		]);
		expect(progress.at(-1)).toMatchObject({ completedEntries: 3, totalEntries: 3 });
		expect(harness.fetchImpl).toHaveBeenCalledTimes(2);
		for (const [, init] of harness.fetchImpl.mock.calls) {
			expect(init).toMatchObject({ cache: "no-store", credentials: "omit" });
		}
		await expect(
			verifyJobsOfflineCache(plan, ready, {
				dependencies: harness.dependencies,
			}),
		).resolves.toBeUndefined();
		const reader = createJobsOfflineCacheReader(
			ready.cacheName,
			harness.cacheStorage,
		);
		await expect(
			reader(new URL(`releases/${plan.releaseId}/jobs/chunks/00000.json`, origin)),
		).resolves.toBeInstanceOf(Response);
	});

	it("fails below 2x quota without opening, deleting, fetching, or replacing readiness", async () => {
		const old = releasePlan("b");
		const plan = releasePlan("c");
		const harness = createHarness(plan, {
			quota: projectedBytes(plan) * 2 - 1,
			usage: 0,
		});
		const previous = readyRecord(old, `${JOBS_OFFLINE_CACHE_PREFIX}${old.releaseId}:old`);
		harness.storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, "true");
		harness.storage.setItem(JOBS_OFFLINE_READY_KEY, JSON.stringify(previous));
		await harness.cacheStorage.open(previous.cacheName);
		await harness.cacheStorage.open("unrelated-app-cache");
		const keysBefore = await harness.cacheStorage.keys();

		await expect(
			prepareJobsOfflineCache(plan, { dependencies: harness.dependencies }),
		).rejects.toMatchObject({ code: "quota" });

		expect(harness.fetchImpl).not.toHaveBeenCalled();
		expect(await harness.cacheStorage.keys()).toEqual(keysBefore);
		expect(readJobsOfflineReady(harness.storage)).toEqual(previous);
	});

	it("rolls back a tampered download and preserves prior and unrelated caches", async () => {
		const old = releasePlan("d");
		const plan = releasePlan("e");
		const harness = createHarness(plan, { tamperPath: "jobs/chunks/00000.json" });
		const previous = readyRecord(old, `${JOBS_OFFLINE_CACHE_PREFIX}${old.releaseId}:old`);
		harness.storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, "true");
		harness.storage.setItem(JOBS_OFFLINE_READY_KEY, JSON.stringify(previous));
		await harness.cacheStorage.open(previous.cacheName);
		await harness.cacheStorage.open("unrelated-app-cache");

		await expect(
			prepareJobsOfflineCache(plan, { dependencies: harness.dependencies }),
		).rejects.toMatchObject({ code: "integrity" });

		expect(readJobsOfflineReady(harness.storage)).toEqual(previous);
		expect(await harness.cacheStorage.keys()).toEqual([
			previous.cacheName,
			"unrelated-app-cache",
		]);
	});

	it("rolls back a partial Cache Storage write without claiming readiness", async () => {
		const plan = releasePlan("f");
		const harness = createHarness(plan, { failPutAt: 2 });
		harness.storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, "true");
		await harness.cacheStorage.open("unrelated-app-cache");

		await expect(
			prepareJobsOfflineCache(plan, { dependencies: harness.dependencies }),
		).rejects.toMatchObject({ code: "storage" });

		expect(readJobsOfflineReady(harness.storage)).toBeNull();
		expect(await harness.cacheStorage.keys()).toEqual(["unrelated-app-cache"]);
	});

	it("retires prior owned releases only after a new release is verified", async () => {
		const old = releasePlan("1");
		const plan = releasePlan("2");
		const harness = createHarness(plan);
		const previous = readyRecord(old, `${JOBS_OFFLINE_CACHE_PREFIX}${old.releaseId}:old`);
		harness.storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, "true");
		harness.storage.setItem(JOBS_OFFLINE_READY_KEY, JSON.stringify(previous));
		await harness.cacheStorage.open(previous.cacheName);
		await harness.cacheStorage.open(`${JOBS_OFFLINE_CACHE_PREFIX}${"3".repeat(64)}:orphan`);
		await harness.cacheStorage.open("unrelated-app-cache");

		const ready = await prepareJobsOfflineCache(plan, {
			dependencies: harness.dependencies,
		});

		expect(readJobsOfflineReady(harness.storage)).toEqual(ready);
		expect(await harness.cacheStorage.keys()).toEqual([
			"unrelated-app-cache",
			ready.cacheName,
		]);
	});

	it("detects cached-byte tampering and never treats an unverified cache as readable", async () => {
		const plan = releasePlan("4");
		const harness = createHarness(plan);
		setJobsOfflineOptIn(true, harness.storage);
		const ready = await prepareJobsOfflineCache(plan, {
			dependencies: harness.dependencies,
		});
		const cache = await harness.cacheStorage.open(ready.cacheName);
		await cache.put(
			new URL(`releases/${plan.releaseId}/jobs/chunks/00000.json`, origin).href,
			new Response("tampered"),
		);

		await expect(
			verifyOrDiscardJobsOfflineCache(plan, ready, {
				dependencies: harness.dependencies,
			}),
		).rejects.toMatchObject({ code: "integrity" });
		expect(readJobsOfflineReady(harness.storage)).toBeNull();
		expect(
			getJobsOfflineSnapshotConfiguration(origin, harness.dependencies),
		).toBeNull();
		expect(await harness.cacheStorage.keys()).not.toContain(ready.cacheName);
	});

	it("opt-out clears every owned release but leaves unrelated Cache Storage entries", async () => {
		const harness = createHarness();
		harness.storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, "true");
		harness.storage.setItem(
			JOBS_OFFLINE_READY_KEY,
			JSON.stringify(
				readyRecord(
					releasePlan("5"),
					`${JOBS_OFFLINE_CACHE_PREFIX}${"5".repeat(64)}:ready`,
				),
			),
		);
		await harness.cacheStorage.open(`${JOBS_OFFLINE_CACHE_PREFIX}${"5".repeat(64)}:ready`);
		await harness.cacheStorage.open(`${JOBS_OFFLINE_CACHE_PREFIX}${"6".repeat(64)}:orphan`);
		await harness.cacheStorage.open("unrelated-app-cache");

		await disableJobsOfflineCache(harness.dependencies);

		expect(isJobsOfflineOptedIn(harness.storage)).toBe(false);
		expect(readJobsOfflineReady(harness.storage)).toBeNull();
		expect(await harness.cacheStorage.keys()).toEqual(["unrelated-app-cache"]);
	});

	it("rejects a projection above its deterministic entry cap before quota or fetch", async () => {
		const files: SnapshotFileEntry[] = Array.from(
			{ length: JOBS_OFFLINE_MAX_ENTRIES },
			(_, index) => fileEntry(`jobs/chunks/${String(index).padStart(5, "0")}.json`, "{}", "jobs-chunk"),
		);
		files.push(fileEntry("search-manifest.json", "{}", "search-manifest"));
		const plan = releasePlan("7", files);
		const harness = createHarness(plan);
		setJobsOfflineOptIn(true, harness.storage);

		await expect(
			prepareJobsOfflineCache(plan, { dependencies: harness.dependencies }),
		).rejects.toMatchObject({ code: "bounded" });
		expect(harness.storageEstimate).not.toHaveBeenCalled();
		expect(harness.fetchImpl).not.toHaveBeenCalled();
	});
});

function releasePlan(
	releaseCharacter = "a",
	files = [
		fileEntry("search-manifest.json", '{"version":6}', "search-manifest"),
		fileEntry("jobs/chunks/00000.json", '{"rows":[]}', "jobs-chunk"),
	],
): SnapshotOfflineReleasePlan {
	const releaseId = releaseCharacter.repeat(64);
	return {
		releaseId,
		snapshotAt: "2026-08-12T12:00:00.000000Z",
		baseUrl: origin,
		manifestPath: `releases/${releaseId}/manifest.json`,
		manifestJson: JSON.stringify({ schemaVersion: 7, releaseId, files }),
		files,
	};
}

function fileEntry(path: string, raw: string, role: string): SnapshotFileEntry {
	return {
		path,
		bytes: new TextEncoder().encode(raw).byteLength,
		mediaType: "application/json",
		sha256: fakeDigest(new TextEncoder().encode(raw)),
		role,
		count: 0,
	};
}

function projectedBytes(plan: SnapshotOfflineReleasePlan) {
	return (
		new TextEncoder().encode(plan.manifestJson).byteLength +
		plan.files.reduce((total, entry) => total + entry.bytes, 0)
	);
}

function readyRecord(
	plan: SnapshotOfflineReleasePlan,
	cacheName: string,
) {
	return {
		schemaVersion: 1 as const,
		releaseId: plan.releaseId,
		snapshotAt: plan.snapshotAt,
		baseUrl: origin,
		cacheName,
		entryCount: plan.files.length + 1,
		totalBytes: projectedBytes(plan),
		readyAt: "2026-08-12T12:00:00.000Z",
	};
}

function createHarness(
	plan?: SnapshotOfflineReleasePlan,
	options: {
		quota?: number;
		usage?: number;
		tamperPath?: string;
		failPutAt?: number;
	} = {},
) {
	const storage = new MemoryStorage();
	const cacheStorage = new MemoryCacheStorage(options.failPutAt);
	const assets = new Map<string, string>();
	if (plan) {
		for (const entry of plan.files) {
			assets.set(
				new URL(`releases/${plan.releaseId}/${entry.path}`, origin).href,
				rawForEntry(entry),
			);
		}
	}
	const fetchImpl = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
		const url = String(input);
		const raw = assets.get(url);
		if (raw === undefined) {
			return new Response(null, { status: 404 });
		}
		const path = new URL(url).pathname.split(`/releases/${plan?.releaseId}/`)[1];
		const body = path === options.tamperPath ? `${raw}x` : raw;
		return new Response(body, {
			headers: { "Content-Length": String(new TextEncoder().encode(body).byteLength) },
		});
	});
	const storageEstimate = vi.fn(async () => ({
		quota: options.quota ?? 1_000_000,
		usage: options.usage ?? 0,
	}));
	return {
		storage,
		cacheStorage,
		fetchImpl,
		storageEstimate,
		dependencies: {
			storage,
			cacheStorage,
			fetchImpl: fetchImpl as typeof fetch,
			storageEstimate,
			digest: async (bytes: Uint8Array) => fakeDigest(bytes),
			now: () => "2026-08-12T12:00:00.000Z",
			token: () => "candidate",
		},
	};
}

function rawForEntry(entry: SnapshotFileEntry) {
	if (entry.path === "search-manifest.json") return '{"version":6}';
	if (entry.path === "jobs/chunks/00000.json") return '{"rows":[]}';
	return "{}";
}

function fakeDigest(bytes: Uint8Array) {
	let hash = 0;
	for (const byte of bytes) hash = (hash * 31 + byte) >>> 0;
	return hash.toString(16).padStart(8, "0").repeat(8);
}

class MemoryStorage implements Storage {
	private readonly values = new Map<string, string>();

	get length() {
		return this.values.size;
	}

	clear() {
		this.values.clear();
	}

	getItem(key: string) {
		return this.values.get(key) ?? null;
	}

	key(index: number) {
		return [...this.values.keys()][index] ?? null;
	}

	removeItem(key: string) {
		this.values.delete(key);
	}

	setItem(key: string, value: string) {
		this.values.set(key, value);
	}
}

class MemoryCache {
	private readonly values = new Map<string, Response>();
	private putCount = 0;

	constructor(private readonly failPutAt?: number) {}

	async keys() {
		return [...this.values.keys()].map((url) => new Request(url));
	}

	async match(input: RequestInfo | URL) {
		return this.values.get(String(input))?.clone();
	}

	async put(input: RequestInfo | URL, response: Response) {
		this.putCount += 1;
		if (this.putCount === this.failPutAt) {
			throw new Error("simulated Cache Storage write failure");
		}
		this.values.set(String(input), response.clone());
	}
}

class MemoryCacheStorage {
	private readonly values = new Map<string, MemoryCache>();

	constructor(private readonly failPutAt?: number) {}

	async delete(name: string) {
		return this.values.delete(name);
	}

	async keys() {
		return [...this.values.keys()];
	}

	async open(name: string) {
		let cache = this.values.get(name);
		if (!cache) {
			cache = new MemoryCache(
				name.startsWith(JOBS_OFFLINE_CACHE_PREFIX) ? this.failPutAt : undefined,
			);
			this.values.set(name, cache);
		}
		return cache as unknown as Cache;
	}
}
