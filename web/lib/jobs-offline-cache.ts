import type { SnapshotFileEntry } from "@/components/openopps-search/search-types";
import type { SnapshotOfflineReleasePlan } from "@/lib/openopps-snapshot-client";

export const JOBS_OFFLINE_CACHE_PREFIX = "openopps-jobs-offline-v1:";
export const JOBS_OFFLINE_OPT_IN_KEY = "openopps.jobs.offline.opt-in.v1";
export const JOBS_OFFLINE_READY_KEY = "openopps.jobs.offline.ready.v1";
export const JOBS_OFFLINE_MAX_ENTRIES = 512;
export const JOBS_OFFLINE_MAX_BYTES = 128 * 1024 * 1024;
export const JOBS_OFFLINE_QUOTA_HEADROOM = 2;

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const CACHEABLE_ROLES = new Set([
	"search-manifest",
	"publication-policy",
	"providers",
	"boards",
	"jobs-bootstrap",
	"jobs-chunk",
	"job-detail-ids",
	"job-indexable-ids",
	"lineage-aggregate",
]);

export type JobsOfflineCacheReady = {
	schemaVersion: 1;
	releaseId: string;
	snapshotAt: string;
	baseUrl: string;
	cacheName: string;
	entryCount: number;
	totalBytes: number;
	readyAt: string;
};

export type JobsOfflineCacheProgress = {
	completedEntries: number;
	totalEntries: number;
	completedBytes: number;
	totalBytes: number;
};

export type JobsOfflineCacheErrorCode =
	| "aborted"
	| "bounded"
	| "fetch"
	| "integrity"
	| "opt_out"
	| "quota"
	| "storage"
	| "unsupported";

export class JobsOfflineCacheError extends Error {
	readonly code: JobsOfflineCacheErrorCode;

	constructor(code: JobsOfflineCacheErrorCode, message: string, options?: ErrorOptions) {
		super(message, options);
		this.name = "JobsOfflineCacheError";
		this.code = code;
	}
}

type CacheStorageLike = Pick<CacheStorage, "delete" | "keys" | "open">;
type PreferenceStorageLike = Pick<Storage, "getItem" | "removeItem" | "setItem">;

export type JobsOfflineCacheDependencies = {
	cacheStorage?: CacheStorageLike;
	storage?: PreferenceStorageLike;
	storageEstimate?: () => Promise<{ quota?: number; usage?: number }>;
	fetchImpl?: typeof fetch;
	digest?: (bytes: Uint8Array) => Promise<string>;
	now?: () => string;
	token?: () => string;
};

export function isJobsOfflineOptedIn(storage = browserStorage()): boolean {
	if (!storage) {
		return false;
	}
	try {
		return storage.getItem(JOBS_OFFLINE_OPT_IN_KEY) === "true";
	} catch {
		return false;
	}
}

export function setJobsOfflineOptIn(
	optedIn: boolean,
	storage = browserStorage(),
): void {
	if (!storage) {
		throw new JobsOfflineCacheError(
			"unsupported",
			"Offline storage is unavailable in this browser.",
		);
	}
	try {
		storage.setItem(JOBS_OFFLINE_OPT_IN_KEY, optedIn ? "true" : "false");
	} catch (caught) {
		throw new JobsOfflineCacheError(
			"storage",
			"The browser could not save the offline preference.",
			{ cause: caught },
		);
	}
}

export function readJobsOfflineReady(
	storage = browserStorage(),
): JobsOfflineCacheReady | null {
	if (!storage) {
		return null;
	}
	let raw: string | null;
	try {
		raw = storage.getItem(JOBS_OFFLINE_READY_KEY);
	} catch {
		return null;
	}
	if (!raw) {
		return null;
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		return isReadyRecord(parsed) ? parsed : null;
	} catch {
		return null;
	}
}

export function getJobsOfflineSnapshotConfiguration(
	baseUrl: URL | string,
	dependencies: Pick<JobsOfflineCacheDependencies, "cacheStorage" | "storage"> = {},
): {
	releaseId: string;
	cacheName: string;
	responseReader: (url: URL) => Promise<Response | null>;
} | null {
	const storage = dependencies.storage ?? browserStorage();
	const cacheStorage = dependencies.cacheStorage ?? browserCacheStorage();
	if (!storage || !cacheStorage || !isJobsOfflineOptedIn(storage)) {
		return null;
	}
	const ready = readJobsOfflineReady(storage);
	if (!ready || ready.baseUrl !== normalizeBaseUrl(baseUrl)) {
		return null;
	}
	return {
		releaseId: ready.releaseId,
		cacheName: ready.cacheName,
		responseReader: createJobsOfflineCacheReader(ready.cacheName, cacheStorage),
	};
}

export function createJobsOfflineCacheReader(
	cacheName: string,
	cacheStorage: CacheStorageLike = requireBrowserCacheStorage(),
) {
	if (!isOwnedCacheName(cacheName)) {
		throw new JobsOfflineCacheError("storage", "Refusing to read an unowned cache.");
	}
	return async (url: URL): Promise<Response | null> => {
		const cache = await cacheStorage.open(cacheName);
		return (await cache.match(url.href)) ?? null;
	};
}

export async function prepareJobsOfflineCache(
	plan: SnapshotOfflineReleasePlan,
	options: {
		dependencies?: JobsOfflineCacheDependencies;
		signal?: AbortSignal;
		onProgress?: (progress: JobsOfflineCacheProgress) => void;
	} = {},
): Promise<JobsOfflineCacheReady> {
	const dependencies = resolveDependencies(options.dependencies);
	if (!isJobsOfflineOptedIn(dependencies.storage)) {
		throw new JobsOfflineCacheError(
			"opt_out",
			"Offline search data is off. Enable it before downloading.",
		);
	}
	const selection = selectCacheEntries(plan);
	throwIfAborted(options.signal);
	await requireQuotaHeadroom(selection.totalBytes, dependencies.storageEstimate);
	throwIfAborted(options.signal);

	const previousReadyRaw = dependencies.storage.getItem(JOBS_OFFLINE_READY_KEY);
	const previousReady = readJobsOfflineReady(dependencies.storage);
	const token = dependencies.token();
	if (!TOKEN_PATTERN.test(token)) {
		throw new JobsOfflineCacheError("storage", "Offline cache token is invalid.");
	}
	const cacheName = `${JOBS_OFFLINE_CACHE_PREFIX}${plan.releaseId}:${token}`;
	await dependencies.cacheStorage.delete(cacheName);

	try {
		const cache = await dependencies.cacheStorage.open(cacheName);
		let completedEntries = 0;
		let completedBytes = 0;
		const reportProgress = () =>
			options.onProgress?.({
				completedEntries,
				totalEntries: selection.entryCount,
				completedBytes,
				totalBytes: selection.totalBytes,
			});
		reportProgress();

		await cacheVerifiedBytes(
			cache,
			selection.manifestUrl,
			selection.manifestBytes,
			"application/json",
		);
		completedEntries += 1;
		completedBytes += selection.manifestBytes.byteLength;
		reportProgress();

		for (const entry of selection.files) {
			throwIfAborted(options.signal);
			const url = releaseFileUrl(plan, entry.path);
			const bytes = await fetchVerifiedFile(
				url,
				entry,
				dependencies.fetchImpl,
				dependencies.digest,
				options.signal,
			);
			await cacheVerifiedBytes(cache, url, bytes, entry.mediaType, entry.sha256);
			completedEntries += 1;
			completedBytes += bytes.byteLength;
			reportProgress();
		}

		await verifyCacheContents(cache, selection, dependencies.digest, options.signal);
		const ready: JobsOfflineCacheReady = {
			schemaVersion: 1,
			releaseId: plan.releaseId,
			snapshotAt: plan.snapshotAt,
			baseUrl: selection.baseUrl,
			cacheName,
			entryCount: selection.entryCount,
			totalBytes: selection.totalBytes,
			readyAt: dependencies.now(),
		};
		dependencies.storage.setItem(JOBS_OFFLINE_READY_KEY, JSON.stringify(ready));

		try {
			await deleteOtherOwnedCaches(
				dependencies.cacheStorage,
				cacheName,
				previousReady?.cacheName ?? null,
			);
		} catch (caught) {
			restoreReadyRecord(dependencies.storage, previousReadyRaw);
			await dependencies.cacheStorage.delete(cacheName).catch(() => false);
			throw new JobsOfflineCacheError(
				"storage",
				"The new release was verified, but the prior owned cache could not be retired.",
				{ cause: caught },
			);
		}

		return ready;
	} catch (caught) {
		restoreReadyRecord(dependencies.storage, previousReadyRaw);
		await dependencies.cacheStorage.delete(cacheName).catch(() => false);
		throw normalizeCacheError(caught);
	}
}

export async function verifyJobsOfflineCache(
	plan: SnapshotOfflineReleasePlan,
	ready: JobsOfflineCacheReady,
	options: {
		dependencies?: Pick<JobsOfflineCacheDependencies, "cacheStorage" | "digest">;
		signal?: AbortSignal;
	} = {},
): Promise<void> {
	const cacheStorage = options.dependencies?.cacheStorage ?? requireBrowserCacheStorage();
	const digest = options.dependencies?.digest ?? sha256Hex;
	const selection = selectCacheEntries(plan);
	if (
		ready.releaseId !== plan.releaseId ||
		ready.baseUrl !== selection.baseUrl ||
		ready.entryCount !== selection.entryCount ||
		ready.totalBytes !== selection.totalBytes ||
		!isOwnedCacheName(ready.cacheName)
	) {
		throw new JobsOfflineCacheError(
			"integrity",
			"The offline cache receipt does not match this release.",
		);
	}
	const cache = await cacheStorage.open(ready.cacheName);
	await verifyCacheContents(cache, selection, digest, options.signal);
}

export async function verifyOrDiscardJobsOfflineCache(
	plan: SnapshotOfflineReleasePlan,
	ready: JobsOfflineCacheReady,
	options: {
		dependencies?: Pick<
			JobsOfflineCacheDependencies,
			"cacheStorage" | "digest" | "storage"
		>;
		signal?: AbortSignal;
	} = {},
): Promise<void> {
	try {
		await verifyJobsOfflineCache(plan, ready, options);
	} catch (caught) {
		const storage = options.dependencies?.storage ?? browserStorage();
		const cacheStorage = options.dependencies?.cacheStorage ?? browserCacheStorage();
		if (storage) {
			const current = readJobsOfflineReady(storage);
			if (current?.cacheName === ready.cacheName) {
				try {
					storage.removeItem(JOBS_OFFLINE_READY_KEY);
				} catch {
					// The failed receipt remains unreadable when Storage itself is blocked.
				}
			}
		}
		if (cacheStorage && isOwnedCacheName(ready.cacheName)) {
			await cacheStorage.delete(ready.cacheName).catch(() => false);
		}
		throw normalizeCacheError(caught);
	}
}

export async function discardJobsOfflineReady(
	ready: JobsOfflineCacheReady,
	dependencies: Pick<JobsOfflineCacheDependencies, "cacheStorage" | "storage"> = {},
): Promise<void> {
	const storage = dependencies.storage ?? browserStorage();
	const cacheStorage = dependencies.cacheStorage ?? browserCacheStorage();
	if (storage) {
		const current = readJobsOfflineReady(storage);
		if (current?.cacheName === ready.cacheName) {
			storage.removeItem(JOBS_OFFLINE_READY_KEY);
		}
	}
	if (cacheStorage && isOwnedCacheName(ready.cacheName)) {
		await cacheStorage.delete(ready.cacheName);
	}
}

export async function disableJobsOfflineCache(
	dependencies: Pick<JobsOfflineCacheDependencies, "cacheStorage" | "storage"> = {},
): Promise<void> {
	const storage = dependencies.storage ?? browserStorage();
	const cacheStorage = dependencies.cacheStorage ?? browserCacheStorage();
	if (!storage) {
		throw new JobsOfflineCacheError(
			"unsupported",
			"Offline storage is unavailable in this browser.",
		);
	}
	setJobsOfflineOptIn(false, storage);
	storage.removeItem(JOBS_OFFLINE_READY_KEY);
	if (!cacheStorage) {
		return;
	}
	for (const cacheName of await cacheStorage.keys()) {
		if (isOwnedCacheName(cacheName)) {
			await cacheStorage.delete(cacheName);
		}
	}
}

type ResolvedDependencies = {
	cacheStorage: CacheStorageLike;
	storage: PreferenceStorageLike;
	storageEstimate: () => Promise<{ quota?: number; usage?: number }>;
	fetchImpl: typeof fetch;
	digest: (bytes: Uint8Array) => Promise<string>;
	now: () => string;
	token: () => string;
};

type CacheSelection = {
	baseUrl: string;
	files: SnapshotFileEntry[];
	manifestUrl: URL;
	manifestBytes: Uint8Array;
	entryCount: number;
	totalBytes: number;
	expectedUrls: string[];
};

function selectCacheEntries(plan: SnapshotOfflineReleasePlan): CacheSelection {
	if (!SHA256_PATTERN.test(plan.releaseId)) {
		throw new JobsOfflineCacheError("integrity", "Offline release ID is invalid.");
	}
	const baseUrl = normalizeBaseUrl(plan.baseUrl);
	if (new URL(baseUrl).protocol !== "https:") {
		throw new JobsOfflineCacheError(
			"integrity",
			"Offline releases require an HTTPS public-data origin.",
		);
	}
	const expectedManifestPath = `releases/${plan.releaseId}/manifest.json`;
	if (plan.manifestPath !== expectedManifestPath) {
		throw new JobsOfflineCacheError(
			"integrity",
			"Offline release manifest path does not match its pinned release.",
		);
	}
	const files = plan.files
		.filter((entry) => CACHEABLE_ROLES.has(entry.role))
		.sort((left, right) => left.path.localeCompare(right.path));
	if (
		files.filter((entry) => entry.role === "search-manifest").length !== 1 ||
		!files.some((entry) => entry.role === "jobs-chunk" || entry.role === "jobs-bootstrap")
	) {
		throw new JobsOfflineCacheError(
			"integrity",
			"Offline release is missing its search manifest or jobs data.",
		);
	}
	const manifestBytes = new TextEncoder().encode(plan.manifestJson);
	const entryCount = files.length + 1;
	const totalBytes = files.reduce((total, entry) => total + entry.bytes, manifestBytes.byteLength);
	if (entryCount > JOBS_OFFLINE_MAX_ENTRIES || totalBytes > JOBS_OFFLINE_MAX_BYTES) {
		throw new JobsOfflineCacheError(
			"bounded",
			`Offline search data exceeds the ${JOBS_OFFLINE_MAX_ENTRIES}-entry or ${JOBS_OFFLINE_MAX_BYTES}-byte safety cap.`,
		);
	}
	const manifestUrl = new URL(expectedManifestPath, baseUrl);
	const expectedUrls = [
		manifestUrl.href,
		...files.map((entry) => releaseFileUrl(plan, entry.path).href),
	].sort();
	if (new Set(expectedUrls).size !== expectedUrls.length) {
		throw new JobsOfflineCacheError("integrity", "Offline release contains duplicate paths.");
	}
	return {
		baseUrl,
		files,
		manifestUrl,
		manifestBytes,
		entryCount,
		totalBytes,
		expectedUrls,
	};
}

async function requireQuotaHeadroom(
	totalBytes: number,
	estimate: () => Promise<{ quota?: number; usage?: number }>,
) {
	let result: { quota?: number; usage?: number };
	try {
		result = await estimate();
	} catch (caught) {
		throw new JobsOfflineCacheError(
			"quota",
			"The browser could not estimate available storage, so offline data was not downloaded.",
			{ cause: caught },
		);
	}
	const quota = result.quota;
	const usage = result.usage;
	if (
		typeof quota !== "number" ||
		!Number.isFinite(quota) ||
		quota < 0 ||
		typeof usage !== "number" ||
		!Number.isFinite(usage) ||
		usage < 0
	) {
		throw new JobsOfflineCacheError(
			"quota",
			"The browser did not provide a reliable storage estimate, so offline data was not downloaded.",
		);
	}
	const availableBytes = Math.max(0, quota - usage);
	const requiredBytes = totalBytes * JOBS_OFFLINE_QUOTA_HEADROOM;
	if (availableBytes < requiredBytes) {
		throw new JobsOfflineCacheError(
			"quota",
			`Offline search needs at least ${requiredBytes} available bytes; the browser reports ${availableBytes}.`,
		);
	}
}

async function fetchVerifiedFile(
	url: URL,
	entry: SnapshotFileEntry,
	fetchImpl: typeof fetch,
	digest: (bytes: Uint8Array) => Promise<string>,
	signal?: AbortSignal,
) {
	let response: Response;
	try {
		response = await fetchImpl(url, {
			cache: "no-store",
			credentials: "omit",
			signal,
		});
	} catch (caught) {
		if (isAbortError(caught)) {
			throw caught;
		}
		throw new JobsOfflineCacheError(
			"fetch",
			`Unable to download ${entry.path}.`,
			{ cause: caught },
		);
	}
	if (!response.ok) {
		throw new JobsOfflineCacheError(
			"fetch",
			`Unable to download ${entry.path}: HTTP ${response.status}.`,
		);
	}
	const contentLength = response.headers.get("content-length");
	if (contentLength !== null) {
		const declaredBytes = Number(contentLength);
		if (Number.isFinite(declaredBytes) && declaredBytes > entry.bytes) {
			throw new JobsOfflineCacheError(
				"integrity",
				`Downloaded byte size exceeds the release manifest for ${entry.path}.`,
			);
		}
	}
	const bytes = await readExactResponseBytes(response, entry.bytes, entry.path);
	if ((await digest(bytes)) !== entry.sha256) {
		throw new JobsOfflineCacheError(
			"integrity",
			`Downloaded bytes do not match the release manifest for ${entry.path}.`,
		);
	}
	return bytes;
}

async function cacheVerifiedBytes(
	cache: Cache,
	url: URL,
	bytes: Uint8Array,
	mediaType: string,
	digest?: string,
) {
	const headers = new Headers({
		"Content-Length": String(bytes.byteLength),
		"Content-Type": mediaType,
	});
	if (digest) {
		headers.set("X-OpenOpps-SHA256", digest);
	}
	await cache.put(url.href, new Response(bytes.slice(), { headers }));
}

async function verifyCacheContents(
	cache: Cache,
	selection: CacheSelection,
	digest: (bytes: Uint8Array) => Promise<string>,
	signal?: AbortSignal,
) {
	throwIfAborted(signal);
	const actualUrls = (await cache.keys()).map((request) => request.url).sort();
	if (
		actualUrls.length !== selection.expectedUrls.length ||
		actualUrls.some((url, index) => url !== selection.expectedUrls[index])
	) {
		throw new JobsOfflineCacheError(
			"integrity",
			"Offline cache entries do not exactly match the pinned release projection.",
		);
	}
	const manifestResponse = await cache.match(selection.manifestUrl.href);
	if (!manifestResponse) {
		throw new JobsOfflineCacheError("integrity", "Offline release manifest is missing.");
	}
	const manifestBytes = await readExactResponseBytes(
		manifestResponse,
		selection.manifestBytes.byteLength,
		"release manifest",
	);
	if (!equalBytes(manifestBytes, selection.manifestBytes)) {
		throw new JobsOfflineCacheError(
			"integrity",
			"Offline release manifest does not match its verified receipt.",
		);
	}
	for (const entry of selection.files) {
		throwIfAborted(signal);
		const response = await cache.match(releaseFileUrlFromSelection(selection, entry.path));
		if (!response) {
			throw new JobsOfflineCacheError("integrity", `Offline entry is missing: ${entry.path}.`);
		}
		const bytes = await readExactResponseBytes(response, entry.bytes, entry.path);
		if ((await digest(bytes)) !== entry.sha256) {
			throw new JobsOfflineCacheError(
				"integrity",
				`Offline entry failed integrity verification: ${entry.path}.`,
			);
		}
	}
}

async function readExactResponseBytes(
	response: Response,
	expectedBytes: number,
	path: string,
) {
	if (!response.body) {
		if (expectedBytes === 0) return new Uint8Array();
		throw new JobsOfflineCacheError(
			"integrity",
			`Offline bytes are missing for ${path}.`,
		);
	}
	const reader = response.body.getReader();
	const chunks: Uint8Array[] = [];
	let totalBytes = 0;
	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			totalBytes += value.byteLength;
			if (totalBytes > expectedBytes) {
				await reader.cancel();
				throw new JobsOfflineCacheError(
					"integrity",
					`Offline byte size exceeds the release manifest for ${path}.`,
				);
			}
			chunks.push(value);
		}
	} finally {
		reader.releaseLock();
	}
	if (totalBytes !== expectedBytes) {
		throw new JobsOfflineCacheError(
			"integrity",
			`Offline byte size does not match the release manifest for ${path}.`,
		);
	}
	const bytes = new Uint8Array(totalBytes);
	let offset = 0;
	for (const chunk of chunks) {
		bytes.set(chunk, offset);
		offset += chunk.byteLength;
	}
	return bytes;
}

async function deleteOtherOwnedCaches(
	cacheStorage: CacheStorageLike,
	keepName: string,
	previousReadyName: string | null,
) {
	const ownedNames = (await cacheStorage.keys()).filter(
		(name) => isOwnedCacheName(name) && name !== keepName,
	);
	const orderedNames = [
		...ownedNames.filter((name) => name !== previousReadyName),
		...ownedNames.filter((name) => name === previousReadyName),
	];
	for (const name of orderedNames) {
		if (!(await cacheStorage.delete(name))) {
			throw new Error(`Unable to delete owned cache ${name}.`);
		}
	}
}

function releaseFileUrl(plan: SnapshotOfflineReleasePlan, path: string) {
	const releaseBase = new URL(`releases/${plan.releaseId}/`, normalizeBaseUrl(plan.baseUrl));
	const url = new URL(path, releaseBase);
	if (url.origin !== releaseBase.origin || !url.pathname.startsWith(releaseBase.pathname)) {
		throw new JobsOfflineCacheError("integrity", `Offline release path is unsafe: ${path}.`);
	}
	return url;
}

function releaseFileUrlFromSelection(selection: CacheSelection, path: string) {
	const manifestUrl = selection.manifestUrl;
	return new URL(path, new URL("./", manifestUrl)).href;
}

function resolveDependencies(
	dependencies: JobsOfflineCacheDependencies = {},
): ResolvedDependencies {
	const cacheStorage = dependencies.cacheStorage ?? browserCacheStorage();
	const storage = dependencies.storage ?? browserStorage();
	const storageEstimate = dependencies.storageEstimate ?? browserStorageEstimate();
	const fetchImpl = dependencies.fetchImpl ?? globalThis.fetch;
	if (
		!cacheStorage ||
		!storage ||
		!storageEstimate ||
		!fetchImpl ||
		(!dependencies.digest && !globalThis.crypto?.subtle) ||
		(!dependencies.token && !globalThis.crypto?.getRandomValues)
	) {
		throw new JobsOfflineCacheError(
			"unsupported",
			"This browser does not support the verified offline cache requirements.",
		);
	}
	return {
		cacheStorage,
		storage,
		storageEstimate,
		fetchImpl,
		digest: dependencies.digest ?? sha256Hex,
		now: dependencies.now ?? (() => new Date().toISOString()),
		token: dependencies.token ?? randomToken,
	};
}

function browserStorage(): PreferenceStorageLike | undefined {
	if (typeof window === "undefined") {
		return undefined;
	}
	try {
		return window.localStorage;
	} catch {
		return undefined;
	}
}

function browserCacheStorage(): CacheStorageLike | undefined {
	return typeof window === "undefined" || typeof window.caches === "undefined"
		? undefined
		: window.caches;
}

function requireBrowserCacheStorage(): CacheStorageLike {
	const cacheStorage = browserCacheStorage();
	if (!cacheStorage) {
		throw new JobsOfflineCacheError("unsupported", "Cache Storage is unavailable.");
	}
	return cacheStorage;
}

function browserStorageEstimate() {
	if (typeof navigator === "undefined" || !navigator.storage?.estimate) {
		return undefined;
	}
	return () => navigator.storage.estimate();
}

function normalizeBaseUrl(baseUrl: URL | string) {
	const parsed = baseUrl instanceof URL ? new URL(baseUrl.href) : new URL(baseUrl);
	return new URL("/", parsed).href;
}

function isReadyRecord(value: unknown): value is JobsOfflineCacheReady {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return false;
	}
	const record = value as Record<string, unknown>;
	return (
		record.schemaVersion === 1 &&
		typeof record.releaseId === "string" &&
		SHA256_PATTERN.test(record.releaseId) &&
		typeof record.snapshotAt === "string" &&
		typeof record.baseUrl === "string" &&
		isHttpsBaseUrl(record.baseUrl) &&
		typeof record.cacheName === "string" &&
		isOwnedCacheName(record.cacheName) &&
		record.cacheName.includes(record.releaseId) &&
		Number.isInteger(record.entryCount) &&
		(record.entryCount as number) > 0 &&
		(record.entryCount as number) <= JOBS_OFFLINE_MAX_ENTRIES &&
		Number.isInteger(record.totalBytes) &&
		(record.totalBytes as number) > 0 &&
		(record.totalBytes as number) <= JOBS_OFFLINE_MAX_BYTES &&
		typeof record.readyAt === "string"
	);
}

function isHttpsBaseUrl(value: string) {
	try {
		const url = new URL(value);
		return url.protocol === "https:" && url.href === new URL("/", url).href;
	} catch {
		return false;
	}
}

function isOwnedCacheName(name: string) {
	return name.startsWith(JOBS_OFFLINE_CACHE_PREFIX);
}

function restoreReadyRecord(storage: PreferenceStorageLike, raw: string | null) {
	try {
		if (raw === null) {
			storage.removeItem(JOBS_OFFLINE_READY_KEY);
		} else {
			storage.setItem(JOBS_OFFLINE_READY_KEY, raw);
		}
	} catch {
		try {
			storage.removeItem(JOBS_OFFLINE_READY_KEY);
		} catch {
			// A blocked Storage implementation cannot be made to claim new readiness.
		}
	}
}

function randomToken() {
	const bytes = new Uint8Array(12);
	globalThis.crypto.getRandomValues(bytes);
	return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(bytes: Uint8Array) {
	const copy = Uint8Array.from(bytes);
	const digest = await globalThis.crypto.subtle.digest("SHA-256", copy.buffer);
	return Array.from(new Uint8Array(digest), (value) =>
		value.toString(16).padStart(2, "0"),
	).join("");
}

function equalBytes(left: Uint8Array, right: Uint8Array) {
	return (
		left.byteLength === right.byteLength &&
		left.every((value, index) => value === right[index])
	);
}

function throwIfAborted(signal?: AbortSignal) {
	if (signal?.aborted) {
		throw signal.reason instanceof Error
			? signal.reason
			: new DOMException("The operation was aborted.", "AbortError");
	}
}

function isAbortError(value: unknown) {
	return value instanceof Error && value.name === "AbortError";
}

function normalizeCacheError(caught: unknown) {
	if (caught instanceof JobsOfflineCacheError) {
		return caught;
	}
	if (isAbortError(caught)) {
		return new JobsOfflineCacheError("aborted", "Offline download was cancelled.", {
			cause: caught,
		});
	}
	return new JobsOfflineCacheError(
		"storage",
		"The browser could not complete the verified offline cache.",
		{ cause: caught },
	);
}
