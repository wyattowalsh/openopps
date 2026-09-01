import type { SearchManifest } from "@/components/openopps-search/search-types";
import { SEARCH_VERSION } from "@/components/openopps-search/search-utils";

export const SNAPSHOT_CHROME_PATH = "/data/openopps-search/snapshot-chrome.json";
export const FACET_CATALOG_PATH = "/data/openopps-search/facet-catalog.json";

export type SnapshotChromeSnapshotCounts = {
	database?: string;
	sourceRows?: number;
	providerRoutes?: number;
	boards?: number;
	jobs?: number;
	openJobs?: number;
};

export type SnapshotChrome = {
	version: number;
	snapshotAt: string | null;
	openJobCount?: number | null;
	kaggleDatasetId?: string;
	source: { database?: string | null };
	counts: { snapshot: SnapshotChromeSnapshotCounts };
	entities: {
		jobs: {
			initialPath?: string;
			file?: string;
			count: number;
			chunkSize?: number;
			chunkCount?: number;
		};
		boards: { count: number };
		providers: { count: number };
	};
	facetSourceCount?: number;
};

export function parseSnapshotChrome(value: unknown): SnapshotChrome {
	if (!isRecord(value)) {
		throw new Error("snapshot-chrome.json is not an object");
	}
	if (value.version === 7) {
		throw new Error("snapshot-chrome.json must not use search payload version 7");
	}
	if (value.version !== SEARCH_VERSION) {
		throw new Error(`snapshot-chrome.json version must be ${SEARCH_VERSION}`);
	}
	if (!(value.snapshotAt === null || typeof value.snapshotAt === "string")) {
		throw new Error("snapshot-chrome.json snapshotAt is invalid");
	}
	const source = isRecord(value.source) ? value.source : {};
	const counts = isRecord(value.counts) ? value.counts : {};
	const snapshot = isRecord(counts.snapshot) ? counts.snapshot : {};
	const entities = isRecord(value.entities) ? value.entities : {};
	const jobs = isRecord(entities.jobs) ? entities.jobs : {};
	const boards = isRecord(entities.boards) ? entities.boards : {};
	const providers = isRecord(entities.providers) ? entities.providers : {};
	if (typeof jobs.count !== "number" || typeof boards.count !== "number" || typeof providers.count !== "number") {
		throw new Error("snapshot-chrome.json entity counts are invalid");
	}
	return {
		version: SEARCH_VERSION,
		snapshotAt: value.snapshotAt,
		openJobCount: typeof value.openJobCount === "number" ? value.openJobCount : null,
		kaggleDatasetId: typeof value.kaggleDatasetId === "string" ? value.kaggleDatasetId : undefined,
		source: { database: typeof source.database === "string" ? source.database : null },
		counts: {
			snapshot: {
				database: typeof snapshot.database === "string" ? snapshot.database : undefined,
				sourceRows: asNumber(snapshot.sourceRows),
				providerRoutes: asNumber(snapshot.providerRoutes),
				boards: asNumber(snapshot.boards),
				jobs: asNumber(snapshot.jobs),
				openJobs: asNumber(snapshot.openJobs),
			},
		},
		entities: {
			jobs: {
				initialPath: typeof jobs.initialPath === "string" ? jobs.initialPath : undefined,
				file: typeof jobs.file === "string" ? jobs.file : undefined,
				count: jobs.count,
				chunkSize: asNumber(jobs.chunkSize),
				chunkCount: asNumber(jobs.chunkCount),
			},
			boards: { count: boards.count },
			providers: { count: providers.count },
		},
		facetSourceCount: asNumber(value.facetSourceCount),
	};
}

export function searchManifestFromChrome(chrome: SnapshotChrome): SearchManifest {
	const database = chrome.source.database ?? "kaggle/openoppsdb.sqlite";
	return {
		version: chrome.version,
		snapshotAt: chrome.snapshotAt,
		openJobCount: chrome.openJobCount ?? undefined,
		kaggleDatasetId: chrome.kaggleDatasetId,
		source: { database, tables: [] },
		counts: {
			snapshot: {
				database: chrome.counts.snapshot.database ?? database,
				sourceRows: chrome.counts.snapshot.sourceRows ?? 0,
				providerRoutes: chrome.counts.snapshot.providerRoutes ?? 0,
				boards: chrome.counts.snapshot.boards ?? chrome.entities.boards.count,
				jobs: chrome.counts.snapshot.jobs ?? chrome.entities.jobs.count,
				openJobs: chrome.counts.snapshot.openJobs ?? chrome.openJobCount ?? 0,
			},
		},
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: {
				path: chrome.entities.jobs.initialPath,
				initialPath: chrome.entities.jobs.initialPath,
				file: chrome.entities.jobs.file,
				count: chrome.entities.jobs.count,
				chunkSize: chrome.entities.jobs.chunkSize,
				columns: [],
			},
			boards: { count: chrome.entities.boards.count, columns: [] },
			providers: { count: chrome.entities.providers.count, columns: [] },
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: [],
			supportLevels: [],
			routeStatuses: [],
			locations: [],
			departments: [],
			teams: [],
			companies: [],
			workplaces: [],
			employmentTypes: [],
			skills: [],
		},
	};
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asNumber(value: unknown): number | undefined {
	return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
