import type {
	JobDetail,
	LineageAggregate,
	SearchChunk,
	SearchManifest,
	SnapshotChannelPointer,
	SnapshotFileEntry,
	SnapshotReleaseManifest,
} from "@/components/openopps-search/search-types";
import {
	EXPECTED_COLUMNS,
	SearchLoadError,
	detailBucket,
	expectedColumnsFor,
} from "@/components/openopps-search/search-utils";
import { resolvePublicSearchUrl } from "@/lib/public-search-url";
import type { ColumnarJobsChunk } from "@/lib/jobs-search-columnar";

const LEGACY_SEARCH_ROOT = "/data/openopps-search";
const LEGACY_SEARCH_MANIFEST_PATH = `${LEGACY_SEARCH_ROOT}/manifest.json`;
const RELEASE_SEARCH_MANIFEST_PATH = "search-manifest.json";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const CHANNEL_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const CANONICAL_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const PORTABLE_PATH_SEGMENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const MAX_RELEASE_FILES = 18_000;
const MAX_RELEASE_FILE_BYTES = 24 * 1024 * 1024;
const MAX_CHANNEL_POINTER_BYTES = 16 * 1024;
const MAX_RELEASE_MANIFEST_BYTES = MAX_RELEASE_FILE_BYTES - 1;
const MAX_PORTABLE_PATH_BYTES = 1_024;

type SnapshotFileReader = (
	publicPath: string,
	signal?: AbortSignal,
) => Promise<string>;

class SnapshotNetworkError extends SearchLoadError {}

export type SnapshotClientOptions = {
	baseUrl: URL | string;
	channel?: string | null;
	/** Already-validated immutable release selected by a trusted caller. */
	pinnedReleaseId?: string | null;
	/** Last verified offline release, used only when mutable-channel network fetch fails. */
	offlineFallbackReleaseId?: string | null;
	/** Reads exact immutable responses from an explicitly-owned browser cache. */
	offlineResponseReader?: (url: URL) => Promise<Response | null>;
	/** Only supplied by trusted server-side legacy adapters. */
	legacyFileReader?: SnapshotFileReader;
	fetchImpl?: typeof fetch;
};

export type SnapshotOfflineReleasePlan = {
	releaseId: string;
	snapshotAt: string;
	baseUrl: string;
	manifestPath: string;
	manifestJson: string;
	files: SnapshotFileEntry[];
};

type LegacySnapshot = {
	kind: "v6";
	cacheKey: string;
};

type ReleaseSnapshot = {
	kind: "v7";
	cacheKey: string;
	manifestPath: string;
	manifest: SnapshotReleaseManifest;
	releaseBase: URL;
	filesByPath: Map<string, SnapshotFileEntry>;
};

type ResolvedSnapshot = LegacySnapshot | ReleaseSnapshot;

/**
 * One release-pinned access boundary for public search metadata, chunks,
 * details, and sitemap ids. A client resolves its mutable channel at most once.
 */
export class OpenOppsSnapshotClient {
	readonly baseUrl: URL;
	readonly channel: string | null;
	readonly pinnedReleaseId: string | null;
	readonly offlineFallbackReleaseId: string | null;
	private readonly legacyFileReader?: SnapshotFileReader;
	private readonly fetchImpl?: typeof fetch;
	private readonly offlineResponseReader?: (url: URL) => Promise<Response | null>;
	private resolvedPromise: Promise<ResolvedSnapshot> | null = null;
	private readonly jsonCache = new Map<string, Promise<unknown>>();

	constructor(options: SnapshotClientOptions) {
		this.baseUrl = normalizeBaseUrl(options.baseUrl);
		this.channel = normalizeChannel(options.channel);
		this.pinnedReleaseId = normalizePinnedReleaseId(options.pinnedReleaseId);
		this.offlineFallbackReleaseId = normalizePinnedReleaseId(
			options.offlineFallbackReleaseId,
		);
		this.legacyFileReader = options.legacyFileReader;
		this.fetchImpl = options.fetchImpl;
		this.offlineResponseReader = options.offlineResponseReader;
		if (
			(this.channel || this.pinnedReleaseId || this.offlineFallbackReleaseId) &&
			this.baseUrl.protocol !== "https:"
		) {
			throw new Error("v7 public-data snapshots require an HTTPS base origin");
		}
	}

	async cacheKey(signal?: AbortSignal) {
		return (await this.resolve(signal)).cacheKey;
	}

	async releaseId(signal?: AbortSignal) {
		const resolved = await this.resolve(signal);
		return resolved.kind === "v7" ? resolved.manifest.releaseId : null;
	}

	/** Trusted, validated immutable inputs for the opt-in browser offline cache. */
	async getOfflineReleasePlan(
		signal?: AbortSignal,
	): Promise<SnapshotOfflineReleasePlan | null> {
		const resolved = await this.resolve(signal);
		if (resolved.kind === "v6") {
			return null;
		}
		return {
			releaseId: resolved.manifest.releaseId,
			snapshotAt: resolved.manifest.snapshotAt,
			baseUrl: this.baseUrl.href,
			manifestPath: resolved.manifestPath,
			manifestJson: JSON.stringify(resolved.manifest),
			files: resolved.manifest.files.map((entry) => ({ ...entry })),
		};
	}

	async getSearchManifest(signal?: AbortSignal): Promise<SearchManifest> {
		const resolved = await this.resolve(signal);
		if (resolved.kind === "v6") {
			const manifest = await this.loadLegacyJson<SearchManifest>(
				LEGACY_SEARCH_MANIFEST_PATH,
				signal,
			);
			validatePayloadSearchManifest(manifest);
			return manifest;
		}
		const matches = resolved.manifest.files.filter(
			(entry) => entry.role === "search-manifest",
		);
		if (
			matches.length !== 1 ||
			matches[0].path !== RELEASE_SEARCH_MANIFEST_PATH
		) {
			throw snapshotError(
				"invalid_manifest",
				"v7 release must contain exactly one search-manifest.json file with role search-manifest",
				resolved.manifestPath,
			);
		}
		const manifest = await this.loadReleaseJson<SearchManifest>(
			resolved,
			RELEASE_SEARCH_MANIFEST_PATH,
			signal,
		);
		validatePayloadSearchManifest(manifest);
		if (manifest.snapshotAt !== resolved.manifest.snapshotAt) {
			throw snapshotError(
				"invalid_manifest",
				"search manifest snapshotAt does not match its pinned release",
				RELEASE_SEARCH_MANIFEST_PATH,
			);
		}
		return manifest;
	}

	async getSnapshotChrome(signal?: AbortSignal) {
		const manifest = await this.getSearchManifest(signal);
		if (manifest.version === 7) {
			throw snapshotError(
				"unsupported_version",
				"snapshot-chrome.json must not use search payload version 7",
				`${LEGACY_SEARCH_ROOT}/snapshot-chrome.json`,
			);
		}
		const publicPath =
			manifest.sidecars?.chrome?.path ?? `${LEGACY_SEARCH_ROOT}/snapshot-chrome.json`;
		const chrome = await this.getSearchAsset<Record<string, unknown>>(
			publicPath,
			signal,
		);
		if (chrome.version === 7) {
			throw snapshotError(
				"unsupported_version",
				"snapshot-chrome.json must not use search payload version 7",
				publicPath,
			);
		}
		if (chrome.version !== 6 && chrome.version !== 3) {
			throw snapshotError(
				"unsupported_version",
				`Unsupported snapshot-chrome version: ${String(chrome.version)}`,
				publicPath,
			);
		}
		return chrome;
	}

	async getSearchAsset<T>(publicPath: string, signal?: AbortSignal): Promise<T> {
		const resolved = await this.resolve(signal);
		if (resolved.kind === "v6") {
			return this.loadLegacyJson<T>(publicPath, signal);
		}
		return this.loadReleaseJson<T>(
			resolved,
			releasePathFromSearchPath(publicPath),
			signal,
		);
	}

	async getSearchChunk(publicPath: string, signal?: AbortSignal) {
		return this.getSearchAsset<SearchChunk>(publicPath, signal);
	}

	async getColumnarJobsChunk(publicPath: string, signal?: AbortSignal) {
		return this.getSearchAsset<ColumnarJobsChunk>(publicPath, signal);
	}

	async getLineageAggregate(
		manifest?: SearchManifest,
		signal?: AbortSignal,
	): Promise<LineageAggregate> {
		const searchManifest = manifest ?? (await this.getSearchManifest(signal));
		const publicPath =
			searchManifest.lineageAggregate?.path ??
			`${LEGACY_SEARCH_ROOT}/lineage-aggregate.json`;
		return this.getSearchAsset<LineageAggregate>(publicPath, signal);
	}

	async getJobDetail(jobId: string, signal?: AbortSignal): Promise<JobDetail | null> {
		let decodedJobId: string;
		try {
			decodedJobId = decodeURIComponent(jobId);
		} catch {
			return null;
		}
		if (!decodedJobId || decodedJobId.includes("\0")) {
			return null;
		}
		const manifest = await this.getSearchManifest(signal);
		const details = manifest.detailShards;
		if (!details?.root) {
			return null;
		}
		const bucket = detailBucket(decodedJobId);
		const publicPath =
			details.buckets?.[bucket]?.path ?? `${details.root}/${bucket}.json`;
		try {
			const records = await this.getSearchAsset<Record<string, JobDetail>>(
				publicPath,
				signal,
			);
			if (!isPlainObject(records)) {
				throw snapshotError(
					"invalid_chunk",
					"job detail shard must be a JSON object",
					publicPath,
				);
			}
			const detail = records[decodedJobId];
			return isPlainObject(detail) && detail.id === decodedJobId
				? (detail as JobDetail)
				: null;
		} catch (caught) {
			if (
				!this.channel &&
				caught instanceof SearchLoadError &&
				((caught.code === "fetch_failed" &&
					/(?:HTTP 404|ENOENT)/.test(caught.message)) ||
					caught.code === "invalid_chunk")
			) {
				return null;
			}
			throw caught;
		}
	}

	async getJobDetailIds(signal?: AbortSignal) {
		const manifest = await this.getSearchManifest(signal);
		const publicPath =
			manifest.detailShards?.idIndexPath ??
			`${LEGACY_SEARCH_ROOT}/jobs-detail-ids.json`;
		return this.loadIdIndex(publicPath, signal);
	}

	async getIndexableJobIds(signal?: AbortSignal) {
		const manifest = await this.getSearchManifest(signal);
		const publicPath = manifest.detailShards?.indexableIdIndexPath;
		if (!publicPath) {
			return [];
		}
		return this.loadIdIndex(publicPath, signal);
	}

	private async loadIdIndex(publicPath: string, signal?: AbortSignal) {
		const value = await this.getSearchAsset<unknown>(publicPath, signal);
		if (
			!isPlainObject(value) ||
			!Number.isInteger(value.count) ||
			!Array.isArray(value.ids) ||
			value.count !== value.ids.length ||
			value.ids.some((id) => typeof id !== "string") ||
			new Set(value.ids).size !== value.ids.length
		) {
			throw snapshotError(
				"invalid_chunk",
				"job id index is invalid",
				publicPath,
			);
		}
		return value.ids as string[];
	}

	private resolve(signal?: AbortSignal): Promise<ResolvedSnapshot> {
		if (!this.resolvedPromise) {
			this.resolvedPromise = this.resolveUncached().catch((caught: unknown) => {
				this.resolvedPromise = null;
				throw caught;
			});
		}
		return awaitWithAbort(this.resolvedPromise, signal);
	}

	private async resolveUncached(): Promise<ResolvedSnapshot> {
		if (this.pinnedReleaseId) {
			return this.resolvePinnedRelease(this.pinnedReleaseId);
		}
		if (!this.channel) {
			return { kind: "v6", cacheKey: `v6|${this.baseUrl.href}` };
		}
		try {
			const pointerPath = `channels/${this.channel}.json`;
			const pointer = await this.fetchUnverifiedJson(
				resolveRootRelativeUrl(this.baseUrl, pointerPath),
				pointerPath,
				{ cache: "no-store" },
				MAX_CHANNEL_POINTER_BYTES,
			);
			validateChannelPointer(pointer, this.channel);
			const manifestPath = pointer.manifestPath;
			const manifest = await this.fetchUnverifiedJson(
				resolveRootRelativeUrl(this.baseUrl, manifestPath),
				manifestPath,
				{ cache: "force-cache" },
				MAX_RELEASE_MANIFEST_BYTES,
			);
			const validated = await validateReleaseManifest(manifest);
			const releaseManifest = validated.manifest;
			const filesByPath = validated.filesByPath;
			validatePointerCoherence(pointer, releaseManifest);
			return releaseSnapshot(
				this.baseUrl,
				manifestPath,
				releaseManifest,
				filesByPath,
			);
		} catch (caught) {
			if (this.offlineFallbackReleaseId && caught instanceof SnapshotNetworkError) {
				return this.resolvePinnedRelease(this.offlineFallbackReleaseId);
			}
			throw caught;
		}
	}

	private async resolvePinnedRelease(releaseId: string) {
		const manifestPath = `releases/${releaseId}/manifest.json`;
		const manifest = await this.fetchUnverifiedJson(
			resolveRootRelativeUrl(this.baseUrl, manifestPath),
			manifestPath,
			{ cache: "force-cache" },
			MAX_RELEASE_MANIFEST_BYTES,
		);
		const validated = await validateReleaseManifest(manifest);
		if (validated.manifest.releaseId !== releaseId) {
			throw snapshotError(
				"invalid_manifest",
				"pinned release ID does not match its immutable manifest",
				manifestPath,
			);
		}
		return releaseSnapshot(
			this.baseUrl,
			manifestPath,
			validated.manifest,
			validated.filesByPath,
		);
	}

	private loadLegacyJson<T>(publicPath: string, signal?: AbortSignal): Promise<T> {
		const path = normalizedLegacySearchPath(publicPath);
		const cacheKey = `v6:${path}`;
		return this.cachedJson(cacheKey, async () => {
			if (this.legacyFileReader) {
				try {
					throwIfAborted(signal);
					const raw = await this.legacyFileReader(path, signal);
					throwIfAborted(signal);
					return parseJson(raw, path) as T;
				} catch (caught) {
					if (isAbortError(caught) || caught instanceof SearchLoadError) {
						throw caught;
					}
					throw snapshotError(
						"fetch_failed",
						`Unable to load ${path}: ${errorMessage(caught)}`,
						path,
					);
				}
			}
			const url = resolvePublicSearchUrl(this.baseUrl, path);
			return (await this.fetchUnverifiedJson(url, path, {
				cache: "force-cache",
				signal,
				priority: "low",
			}, MAX_RELEASE_FILE_BYTES)) as T;
		});
	}

	private loadReleaseJson<T>(
		resolved: ReleaseSnapshot,
		relativePath: string,
		signal?: AbortSignal,
	): Promise<T> {
		const path = normalizedSafeRelativePath(relativePath);
		const entry = resolved.filesByPath.get(path);
		if (!entry) {
			throw snapshotError(
				"invalid_manifest",
				`release asset is not declared by the pinned manifest: ${path}`,
				path,
			);
		}
		if (entry.mediaType !== "application/json") {
			throw snapshotError(
				"invalid_manifest",
				`release asset is not JSON: ${path}`,
				path,
			);
		}
		const cacheKey = `${resolved.manifest.releaseId}:${path}`;
		return this.cachedJson(cacheKey, async () => {
			const url = new URL(path, resolved.releaseBase);
			if (
				url.origin !== resolved.releaseBase.origin ||
				!url.pathname.startsWith(resolved.releaseBase.pathname)
			) {
				throw snapshotError(
					"invalid_manifest",
					`release path escapes its pinned base: ${path}`,
					path,
				);
			}
			const response = await this.fetchResponse(url, path, {
				cache: "force-cache",
				signal,
			});
			const bytes = await readBoundedResponseBytes(
				response,
				entry.bytes,
				path,
				MAX_RELEASE_FILE_BYTES - 1,
			);
			if (bytes.byteLength !== entry.bytes) {
				throw snapshotError(
					"invalid_chunk",
					`release asset byte size does not match manifest: ${path}`,
					path,
				);
			}
			const digest = await sha256Hex(bytes);
			if (digest !== entry.sha256) {
				throw snapshotError(
					"invalid_chunk",
					`release asset SHA-256 does not match manifest: ${path}`,
					path,
				);
			}
			return parseJson(new TextDecoder("utf-8", { fatal: true }).decode(bytes), path) as T;
		});
	}

	private cachedJson<T>(key: string, loader: () => Promise<T>): Promise<T> {
		let cached = this.jsonCache.get(key) as Promise<T> | undefined;
		if (!cached) {
			cached = loader().catch((caught: unknown) => {
				if (this.jsonCache.get(key) === cached) {
					this.jsonCache.delete(key);
				}
				throw caught;
			});
			this.jsonCache.set(key, cached);
		}
		return cached;
	}

	private async fetchUnverifiedJson(
		url: URL,
		path: string,
		init: RequestInit,
		maxBytes: number,
	): Promise<unknown> {
		const response = await this.fetchResponse(url, path, init);
		try {
			const bytes = await readBoundedResponseBytes(response, maxBytes, path);
			return parseJson(
				new TextDecoder("utf-8", { fatal: true }).decode(bytes),
				path,
			);
		} catch (caught) {
			throw snapshotError(
				"invalid_manifest",
				`Unable to parse ${path}: ${errorMessage(caught)}`,
				path,
			);
		}
	}

	private async fetchResponse(url: URL, path: string, init: RequestInit) {
		throwIfAborted(init.signal ?? undefined);
		if (this.offlineResponseReader) {
			try {
				const cached = await this.offlineResponseReader(url);
				throwIfAborted(init.signal ?? undefined);
				if (cached) {
					return cached;
				}
			} catch (caught) {
				if (isAbortError(caught)) {
					throw caught;
				}
				// Cache API failures do not suppress an otherwise-available network read.
			}
		}
		let response: Response;
		try {
			response = await (this.fetchImpl ?? globalThis.fetch)(url, init);
		} catch (caught) {
			if (isAbortError(caught)) {
				throw caught;
			}
			throw new SnapshotNetworkError(
				"fetch_failed",
				`Unable to load ${path}: ${errorMessage(caught)}`,
				path,
			);
		}
		if (!response.ok) {
			throw snapshotError(
				"fetch_failed",
				`Unable to load ${path}: HTTP ${response.status}`,
				path,
			);
		}
		return response;
	}
}

function normalizeBaseUrl(baseUrl: URL | string) {
	const parsed = baseUrl instanceof URL ? new URL(baseUrl.href) : new URL(baseUrl);
	return new URL("/", parsed);
}

function normalizeChannel(channel: string | null | undefined) {
	const value = channel?.trim() ?? "";
	if (!value) {
		return null;
	}
	if (!CHANNEL_PATTERN.test(value)) {
		throw new Error("public-data channel must be a safe lowercase channel name");
	}
	return value;
}

function normalizePinnedReleaseId(value: string | null | undefined) {
	const releaseId = value?.trim() ?? "";
	if (!releaseId) {
		return null;
	}
	if (!isSha256(releaseId)) {
		throw new Error("pinned public-data release ID must be a lowercase SHA-256 digest");
	}
	return releaseId;
}

function releaseSnapshot(
	baseUrl: URL,
	manifestPath: string,
	manifest: SnapshotReleaseManifest,
	filesByPath: Map<string, SnapshotFileEntry>,
): ReleaseSnapshot {
	return {
		kind: "v7",
		cacheKey: `v7|${baseUrl.href}|${manifest.releaseId}`,
		manifestPath,
		manifest,
		releaseBase: new URL(`/releases/${manifest.releaseId}/`, baseUrl),
		filesByPath,
	};
}

function validateChannelPointer(
	value: unknown,
	expectedChannel: string,
): asserts value is SnapshotChannelPointer {
	if (!isPlainObject(value) || !hasExactKeys(value, [
		"schemaVersion",
		"channel",
		"releaseId",
		"rootDigest",
		"snapshotAt",
		"manifestPath",
		"priorReleaseId",
		"degradedReason",
		"promotedAt",
		"snapshotAgeSeconds",
	])) {
		throw snapshotError("invalid_manifest", "channel pointer has unexpected or missing fields");
	}
	if (
		value.schemaVersion !== 2 ||
		value.channel !== expectedChannel ||
		!isSha256(value.releaseId) ||
		!isRootDigest(value.rootDigest) ||
		value.rootDigest.value !== value.releaseId ||
		!isCanonicalUtc(value.snapshotAt) ||
		value.manifestPath !== `releases/${value.releaseId}/manifest.json` ||
		!(value.priorReleaseId === null ||
			(isSha256(value.priorReleaseId) && value.priorReleaseId !== value.releaseId)) ||
		!(value.degradedReason === null ||
			(typeof value.degradedReason === "string" &&
				value.degradedReason.trim().length > 0 &&
				value.degradedReason.length <= 500)) ||
		!isCanonicalUtc(value.promotedAt) ||
		!Number.isSafeInteger(value.snapshotAgeSeconds) ||
		(value.snapshotAgeSeconds as number) < 0
	) {
		throw snapshotError("invalid_manifest", "channel pointer is invalid or incoherent");
	}
	const promotedAt = Date.parse(value.promotedAt as string);
	const snapshotAt = Date.parse(value.snapshotAt as string);
	const expectedAge = Math.trunc((promotedAt - snapshotAt) / 1_000);
	if (
		!Number.isSafeInteger(expectedAge) ||
		expectedAge < 0 ||
		value.snapshotAgeSeconds !== expectedAge
	) {
		throw snapshotError(
			"invalid_manifest",
			"channel pointer snapshotAgeSeconds does not match promotedAt minus snapshotAt",
		);
	}
}

async function validateReleaseManifest(
	value: unknown,
): Promise<{
	manifest: SnapshotReleaseManifest;
	filesByPath: Map<string, SnapshotFileEntry>;
}> {
	if (!isPlainObject(value) || !hasExactKeys(value, [
		"schemaVersion",
		"snapshotAt",
		"source",
		"generator",
		"fileCount",
		"totalBytes",
		"files",
		"releaseId",
		"rootDigest",
	])) {
		throw snapshotError("invalid_manifest", "release manifest has unexpected or missing fields");
	}
	if (
		value.schemaVersion !== 7 ||
		!isCanonicalUtc(value.snapshotAt) ||
		!isSha256(value.releaseId) ||
		!isRootDigest(value.rootDigest) ||
		value.rootDigest.value !== value.releaseId ||
		!Number.isSafeInteger(value.fileCount) ||
		(value.fileCount as number) < 1 ||
		!Number.isSafeInteger(value.totalBytes) ||
		(value.totalBytes as number) < 0 ||
		!Array.isArray(value.files) ||
		value.fileCount !== value.files.length ||
		!validSource(value.source) ||
		!validGenerator(value.generator)
	) {
		throw snapshotError("invalid_manifest", "release manifest is invalid");
	}
	if ((value.fileCount as number) > MAX_RELEASE_FILES) {
		throw snapshotError(
			"invalid_manifest",
			`release manifest exceeds ${MAX_RELEASE_FILES} file entries`,
		);
	}
	const filesByPath = new Map<string, SnapshotFileEntry>();
	const casefoldedPaths = new Set<string>();
	let totalBytes = 0;
	for (const candidate of value.files) {
		if (!validFileEntry(candidate)) {
			throw snapshotError("invalid_manifest", "release manifest contains an invalid file entry");
		}
		if (candidate.bytes >= MAX_RELEASE_FILE_BYTES) {
			throw snapshotError(
				"invalid_manifest",
				`release file must be smaller than ${MAX_RELEASE_FILE_BYTES} bytes: ${candidate.path}`,
				candidate.path,
			);
		}
		const path = normalizedSafeRelativePath(candidate.path);
		const folded = path.toLowerCase();
		if (filesByPath.has(path) || casefoldedPaths.has(folded)) {
			throw snapshotError("invalid_manifest", `release manifest contains a duplicate path: ${path}`);
		}
		filesByPath.set(path, candidate);
		casefoldedPaths.add(folded);
		totalBytes += candidate.bytes;
	}
	if (totalBytes !== value.totalBytes) {
		throw snapshotError("invalid_manifest", "release manifest totalBytes is inconsistent");
	}
	const body = {
		fileCount: value.fileCount,
		files: value.files,
		generator: value.generator,
		schemaVersion: value.schemaVersion,
		snapshotAt: value.snapshotAt,
		source: value.source,
		totalBytes: value.totalBytes,
	};
	if ((await sha256Text(stableCanonicalJson(body))) !== value.releaseId) {
		throw snapshotError("invalid_manifest", "releaseId does not match the canonical manifest body");
	}
	return {
		manifest: value as unknown as SnapshotReleaseManifest,
		filesByPath,
	};
}

function validatePointerCoherence(
	pointer: SnapshotChannelPointer,
	manifest: SnapshotReleaseManifest,
) {
	if (
		pointer.releaseId !== manifest.releaseId ||
		pointer.rootDigest.value !== manifest.rootDigest.value ||
		pointer.snapshotAt !== manifest.snapshotAt
	) {
		throw snapshotError(
			"invalid_manifest",
			"channel pointer does not match its release manifest",
			pointer.manifestPath,
		);
	}
}

function validatePayloadSearchManifest(
	value: unknown,
): asserts value is SearchManifest {
	if (
		!isPlainObject(value) ||
		(value.version !== 3 && value.version !== 6) ||
		!(value.snapshotAt === null || typeof value.snapshotAt === "string") ||
		!isPlainObject(value.source) ||
		typeof value.source.database !== "string" ||
		!isStringArray(value.source.tables) ||
		(value.defaultEntity !== "jobs" &&
			value.defaultEntity !== "boards" &&
			value.defaultEntity !== "providers") ||
		!isPlainObject(value.defaultFilters) ||
		!isPlainObject(value.defaultFilters.jobs) ||
		typeof value.defaultFilters.jobs.status !== "string" ||
		!isPlainObject(value.entities) ||
		!isPlainObject(value.facets)
	) {
		throw snapshotError("invalid_manifest", "search manifest has invalid required fields");
	}
	for (const entity of Object.keys(EXPECTED_COLUMNS) as Array<keyof typeof EXPECTED_COLUMNS>) {
		const details = value.entities[entity];
		if (
			!isPlainObject(details) ||
			!Number.isSafeInteger(details.count) ||
			(details.count as number) < 0 ||
			!isStringArray(details.columns) ||
			details.columns.join("\0") !==
				expectedColumnsFor(entity, value.version as number).join("\0")
		) {
			throw snapshotError(
				"invalid_manifest",
				`search manifest has invalid ${entity} metadata`,
			);
		}
		for (const key of ["path", "initialPath", "detailPath"] as const) {
			const publicPath = details[key];
			if (publicPath !== undefined) {
				if (typeof publicPath !== "string") {
					throw snapshotError("invalid_manifest", `${entity}.${key} must be a string`);
				}
				if (key === "detailPath") {
					normalizedLegacySearchTemplatePath(publicPath);
				} else {
					normalizedLegacySearchPath(publicPath);
				}
			}
		}
		if (details.chunks !== undefined) {
			if (!Array.isArray(details.chunks)) {
				throw snapshotError("invalid_manifest", `${entity}.chunks must be an array`);
			}
			const indices = new Set<number>();
			for (const chunk of details.chunks) {
				if (
					!isPlainObject(chunk) ||
					!Number.isSafeInteger(chunk.index) ||
					(chunk.index as number) < 0 ||
					indices.has(chunk.index as number) ||
					typeof chunk.path !== "string" ||
					typeof chunk.file !== "string" ||
					!Number.isSafeInteger(chunk.count) ||
					(chunk.count as number) < 0
				) {
					throw snapshotError("invalid_manifest", `${entity} has an invalid chunk reference`);
				}
				indices.add(chunk.index as number);
				normalizedLegacySearchPath(chunk.path);
			}
		}
	}
	for (const facet of Object.values(value.facets)) {
		if (!isStringArray(facet)) {
			throw snapshotError("invalid_manifest", "search manifest facets must be string arrays");
		}
	}
	if (value.lineageAggregate !== undefined) {
		if (
			!isPlainObject(value.lineageAggregate) ||
			typeof value.lineageAggregate.path !== "string"
		) {
			throw snapshotError("invalid_manifest", "lineage aggregate reference is invalid");
		}
		normalizedLegacySearchPath(value.lineageAggregate.path);
	}
	if (value.detailShards !== undefined) {
		if (
			!isPlainObject(value.detailShards) ||
			typeof value.detailShards.root !== "string" ||
			!Number.isSafeInteger(value.detailShards.bucketCount) ||
			(value.detailShards.bucketCount as number) < 1 ||
			!Number.isSafeInteger(value.detailShards.count) ||
			(value.detailShards.count as number) < 0
		) {
			throw snapshotError("invalid_manifest", "detail shard metadata is invalid");
		}
		normalizedLegacySearchPath(value.detailShards.root);
		for (const key of ["idIndexPath", "indexableIdIndexPath"] as const) {
			const publicPath = value.detailShards[key];
			if (publicPath !== undefined) {
				if (typeof publicPath !== "string") {
					throw snapshotError("invalid_manifest", `detailShards.${key} must be a string`);
				}
				normalizedLegacySearchPath(publicPath);
			}
		}
		if (value.detailShards.buckets !== undefined) {
			if (!isPlainObject(value.detailShards.buckets)) {
				throw snapshotError("invalid_manifest", "detail shard buckets are invalid");
			}
			for (const bucket of Object.values(value.detailShards.buckets)) {
				if (
					!isPlainObject(bucket) ||
					typeof bucket.path !== "string" ||
					!Number.isSafeInteger(bucket.count) ||
					(bucket.count as number) < 0
				) {
					throw snapshotError("invalid_manifest", "detail shard bucket is invalid");
				}
				normalizedLegacySearchPath(bucket.path);
			}
		}
	}
}

function isStringArray(value: unknown): value is string[] {
	return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function validSource(value: unknown) {
	return (
		isPlainObject(value) &&
		hasExactKeys(value, ["kind", "path", "bytes", "sha256"]) &&
		value.kind === "sqlite" &&
		typeof value.path === "string" &&
		isSafeRelativePath(value.path) &&
		Number.isSafeInteger(value.bytes) &&
		(value.bytes as number) >= 0 &&
		isSha256(value.sha256)
	);
}

function validGenerator(value: unknown) {
	return (
		isPlainObject(value) &&
		hasExactKeys(value, ["name", "entrypoint", "components", "payloadSchemaVersion"]) &&
		typeof value.name === "string" &&
		value.name.length > 0 &&
		typeof value.entrypoint === "string" &&
		isSafeRelativePath(value.entrypoint) &&
		Number.isSafeInteger(value.payloadSchemaVersion) &&
		Array.isArray(value.components) &&
		value.components.length > 0 &&
		value.components.every(
			(component) =>
				isPlainObject(component) &&
				hasExactKeys(component, ["path", "sha256"]) &&
				typeof component.path === "string" &&
				isSafeRelativePath(component.path) &&
				isSha256(component.sha256),
		)
	);
}

function validFileEntry(value: unknown): value is SnapshotFileEntry {
	return (
		isPlainObject(value) &&
		hasExactKeys(value, ["path", "bytes", "mediaType", "sha256", "role", "count"]) &&
		typeof value.path === "string" &&
		isSafeRelativePath(value.path) &&
		Number.isSafeInteger(value.bytes) &&
		(value.bytes as number) >= 0 &&
		typeof value.mediaType === "string" &&
		value.mediaType.length > 0 &&
		isSha256(value.sha256) &&
		typeof value.role === "string" &&
		value.role.length > 0 &&
		Number.isSafeInteger(value.count) &&
		(value.count as number) >= 0
	);
}

function isRootDigest(value: unknown): value is { algorithm: "sha256"; value: string } {
	return (
		isPlainObject(value) &&
		hasExactKeys(value, ["algorithm", "value"]) &&
		value.algorithm === "sha256" &&
		isSha256(value.value)
	);
}

function normalizedLegacySearchPath(value: string) {
	const trimmed = value.trim();
	if (trimmed === LEGACY_SEARCH_ROOT || !trimmed.startsWith(`${LEGACY_SEARCH_ROOT}/`)) {
		throw snapshotError(
			"invalid_manifest",
			`public search path must be under ${LEGACY_SEARCH_ROOT}/`,
			value,
		);
	}
	normalizedSafeRelativePath(trimmed.slice(LEGACY_SEARCH_ROOT.length + 1));
	return trimmed;
}

function releasePathFromSearchPath(value: string) {
	return normalizedLegacySearchPath(value).slice(LEGACY_SEARCH_ROOT.length + 1);
}

function normalizedLegacySearchTemplatePath(value: string) {
	if ((value.match(/\{bucket\}/g) ?? []).length !== 1) {
		throw snapshotError(
			"invalid_manifest",
			"detail path template must contain exactly one {bucket} placeholder",
			value,
		);
	}
	if (/[{}]/.test(value.replace("{bucket}", ""))) {
		throw snapshotError(
			"invalid_manifest",
			"detail path template contains an unsupported placeholder",
			value,
		);
	}
	return normalizedLegacySearchPath(value.replace("{bucket}", "00"));
}

function normalizedSafeRelativePath(value: string) {
	if (!isSafeRelativePath(value)) {
		throw snapshotError("invalid_manifest", `unsafe release asset path: ${value}`, value);
	}
	return value;
}

function isSafeRelativePath(value: string) {
	const encodedLength = new TextEncoder().encode(value).byteLength;
	if (
		!value ||
		encodedLength > MAX_PORTABLE_PATH_BYTES ||
		value.startsWith("/") ||
		value.includes("\\") ||
		value.includes("\0") ||
		value.includes("%") ||
		/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value)
	) {
		return false;
	}
	const parts = value.split("/");
	return parts.every(
		(part) =>
			part !== "" &&
			part !== "." &&
			part !== ".." &&
			PORTABLE_PATH_SEGMENT_PATTERN.test(part),
	);
}

function resolveRootRelativeUrl(base: URL, relativePath: string) {
	const path = normalizedSafeRelativePath(relativePath);
	const resolved = new URL(`/${path}`, base);
	if (resolved.origin !== base.origin) {
		throw snapshotError("invalid_manifest", `snapshot path escapes base origin: ${path}`, path);
	}
	return resolved;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]) {
	const actual = Object.keys(value).sort();
	const expected = [...keys].sort();
	return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isSha256(value: unknown): value is string {
	return typeof value === "string" && SHA256_PATTERN.test(value);
}

function isCanonicalUtc(value: unknown): value is string {
	return (
		typeof value === "string" &&
		CANONICAL_UTC_PATTERN.test(value) &&
		Number.isFinite(Date.parse(value))
	);
}

function stableCanonicalJson(value: unknown): string {
	if (value === null || typeof value !== "object") {
		return JSON.stringify(value);
	}
	if (Array.isArray(value)) {
		return `[${value.map(stableCanonicalJson).join(",")}]`;
	}
	return `{${Object.entries(value as Record<string, unknown>)
		.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
		.map(([key, item]) => `${JSON.stringify(key)}:${stableCanonicalJson(item)}`)
		.join(",")}}`;
}

async function sha256Text(value: string) {
	return sha256Hex(new TextEncoder().encode(value));
}

async function sha256Hex(bytes: Uint8Array) {
	const subtle = globalThis.crypto?.subtle;
	if (!subtle) {
		throw new Error("Web Crypto SHA-256 support is required for v7 snapshots");
	}
	const input = bytes.slice().buffer as ArrayBuffer;
	const digest = new Uint8Array(await subtle.digest("SHA-256", input));
	return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function parseJson(raw: string, path: string) {
	try {
		return JSON.parse(raw) as unknown;
	} catch (caught) {
		throw snapshotError(
			"invalid_chunk",
			`Unable to parse ${path}: ${errorMessage(caught)}`,
			path,
		);
	}
}

async function readBoundedResponseBytes(
	response: Response,
	maxBytes: number,
	path: string,
	maxAdvertisedBytes = maxBytes,
) {
	const contentLength = response.headers.get("content-length");
	if (contentLength !== null) {
		if (!/^\d+$/.test(contentLength)) {
			throw snapshotError(
				"invalid_chunk",
				`Unable to load ${path}: invalid Content-Length`,
				path,
			);
		}
		const advertisedBytes = Number(contentLength);
		if (
			!Number.isSafeInteger(advertisedBytes) ||
			advertisedBytes > maxAdvertisedBytes
		) {
			throw snapshotError(
				"invalid_chunk",
				`Unable to load ${path}: response exceeds ${maxAdvertisedBytes} byte budget`,
				path,
			);
		}
	}
	if (!response.body) {
		throw snapshotError(
			"invalid_chunk",
			`Unable to load ${path}: response body is unavailable`,
			path,
		);
	}
	const chunks: Uint8Array[] = [];
	let totalBytes = 0;
	const reader = response.body.getReader();
	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) {
				break;
			}
			totalBytes += value.byteLength;
			if (totalBytes > maxBytes) {
				await reader.cancel("OpenOpps response byte budget exceeded");
				throw snapshotError(
					"invalid_chunk",
					`Unable to load ${path}: response exceeds ${maxBytes} byte budget`,
					path,
				);
			}
			chunks.push(value);
		}
	} finally {
		reader.releaseLock();
	}
	const bytes = new Uint8Array(totalBytes);
	let offset = 0;
	for (const chunk of chunks) {
		bytes.set(chunk, offset);
		offset += chunk.byteLength;
	}
	return bytes;
}

function snapshotError(
	code: ConstructorParameters<typeof SearchLoadError>[0],
	message: string,
	path?: string,
) {
	return new SearchLoadError(code, message, path);
}

function throwIfAborted(signal?: AbortSignal | null) {
	if (signal?.aborted) {
		throw new DOMException("The operation was aborted.", "AbortError");
	}
}

function awaitWithAbort<T>(promise: Promise<T>, signal?: AbortSignal) {
	if (!signal) {
		return promise;
	}
	throwIfAborted(signal);
	return new Promise<T>((resolve, reject) => {
		const abort = () => reject(new DOMException("The operation was aborted.", "AbortError"));
		signal.addEventListener("abort", abort, { once: true });
		promise.then(
			(value) => {
				signal.removeEventListener("abort", abort);
				resolve(value);
			},
			(caught) => {
				signal.removeEventListener("abort", abort);
				reject(caught);
			},
		);
	});
}

function isAbortError(value: unknown) {
	return value instanceof Error && value.name === "AbortError";
}

function errorMessage(value: unknown) {
	return value instanceof Error ? `${value.name}: ${value.message || "(empty message)"}` : String(value);
}
