/** Search index entity tab: jobs, boards, or board providers. */
export type Entity = "jobs" | "boards" | "providers";

/** Compact row tuple aligned with manifest `columns` order. */
export type SearchRow = Array<string | number | null>;

/** On-disk chunk reference in the generated search manifest. */
export type SearchChunkRef = {
	index: number;
	path: string;
	file: string;
	count: number;
};

/** Per-entity manifest slice: paths, column order, counts, and optional chunk list. */
export type SearchEntityManifest = {
	path?: string;
	file?: string;
	initialPath?: string;
	chunkSize?: number;
	columns: string[];
	count: number;
	detailPath?: string;
	chunks?: SearchChunkRef[];
};

export type SearchSuggestion = {
	value: string;
	label: string;
	count: number;
	normalized: string;
	aliases?: string[];
};

export type SearchTopValue = {
	value: string;
	count: number;
};

export type SearchQualityMetric = {
	key: string;
	count: number;
	total: number;
	percentage: number;
};

export type SearchDashboard = {
	snapshotAt: string | null;
	totals: {
		sourceRows: number;
		providerRoutes: number;
		boards: number;
		jobs: number;
		openJobs: number;
	};
	top: {
		sourcesByJobs: SearchTopValue[];
		providersByJobs: SearchTopValue[];
		locations: SearchTopValue[];
		departments: SearchTopValue[];
		teams: SearchTopValue[];
		companies: SearchTopValue[];
		skills: SearchTopValue[];
	};
	dataQuality: SearchQualityMetric[];
	routeHealth: {
		supportLevels: SearchTopValue[];
		routeStatuses: SearchTopValue[];
	};
	artifacts: {
		jobChunks: number;
		detailShardBuckets: number;
		detailShardRecords: number;
		detailShardTiers?: Record<string, number>;
	};
	sync?: {
		windowDays: number;
		windowStart: string | null;
		runCount: number;
		totals7d: {
			new: number;
			changed: number;
			closed: number;
			reopened: number;
		};
		medianDaysOpenByProvider: Array<{
			providerId: string;
			medianDaysOpen: number;
			count: number;
		}>;
		topBoardsByChurn: Array<{
			boardKey: string;
			providerId: string;
			closedCount: number;
		}>;
	};
};

export type LineageNode = {
	id: string;
	label?: string | null;
	sourceKey?: string | null;
	name?: string | null;
	domain?: string | null;
	routes?: number;
	jobs: number;
	openJobs: number;
	closedJobs?: number;
	latestObservedAt?: string | null;
	sourcesCount?: number;
	providersCount?: number;
	boardsCount?: number;
	sources?: string[];
	providers?: string[];
	boards?: string[];
	supportLevels?: SearchTopValue[];
	routeStatuses?: SearchTopValue[];
	quality?: {
		description: number;
		locations: number;
		compensation: number;
	};
};

export type LineageEdge = {
	sourceKey?: string | null;
	providerId?: string | null;
	boardKey?: string | null;
	routes?: number;
	boards?: number;
	jobs: number;
	openJobs: number;
	supportLevels?: SearchTopValue[];
	routeStatuses?: SearchTopValue[];
};

export type LineageAggregate = {
	version: number;
	snapshotAt: string | null;
	counts: {
		sourceRows: number;
		sources: number;
		providerRoutes: number;
		providers: number;
		boards: number;
		jobs: number;
		openJobs: number;
	};
	nodes: {
		sources: LineageNode[];
		providers: LineageNode[];
		boards: LineageNode[];
	};
	edges: {
		sourceProviders: LineageEdge[];
		sourceBoards: LineageEdge[];
		providerBoards: LineageEdge[];
	};
	artifacts?: {
		jobChunks: number;
		detailShardBuckets: number;
		detailShardRecords: number;
		detailShardTiers?: Record<string, number>;
	};
};

export type LineageAggregateRef = {
	path: string;
	file?: string;
	count?: LineageAggregate["counts"];
};

/** Root manifest served from `/search/manifest.json`. */
export type SearchManifest = {
	version: number;
	snapshotAt: string | null;
	openJobCount?: number;
	counts?: {
		catalog?: {
			source: string;
			note?: string;
		};
		snapshot?: {
			database: string;
			sourceRows: number;
			providerRoutes: number;
			boards: number;
			jobs: number;
			openJobs: number;
		};
	};
	kaggleDatasetId?: string;
	source: {
		database: string;
		tables: string[];
	};
	defaultEntity: Entity;
	defaultFilters: { jobs: { status: string } };
	filterSpec?: Record<string, string>;
	detailShards?: {
		root: string;
		format?: "bucket-map";
		idIndexPath?: string;
		idIndexFile?: string;
		indexableIdIndexPath?: string;
		indexableIdIndexFile?: string;
		indexableCount?: number;
		bucketCount: number;
		count: number;
		buckets?: Record<string, { path: string; count: number }>;
	};
	entities: Record<Entity, SearchEntityManifest>;
	facets: {
		sources: string[];
		providerIds: string[];
		jobStatuses: string[];
		supportLevels: string[];
		routeStatuses: string[];
		workplaces: string[];
		employmentTypes: string[];
		locations?: string[];
		departments?: string[];
		teams?: string[];
		companies?: string[];
		skills?: string[];
		salaryCurrencies?: string[];
		seniorities?: string[];
	};
	suggestions?: {
		sources?: SearchSuggestion[];
		providers?: SearchSuggestion[];
		locations?: SearchSuggestion[];
		departments?: SearchSuggestion[];
		teams?: SearchSuggestion[];
		companies?: SearchSuggestion[];
		skills?: SearchSuggestion[];
		workplaces?: SearchSuggestion[];
		employmentTypes?: SearchSuggestion[];
		jobStatuses?: SearchSuggestion[];
		salaryCurrencies?: SearchSuggestion[];
	};
	dashboard?: SearchDashboard;
	lineageAggregate?: LineageAggregateRef;
};

/** Loaded entity chunk: column order plus materialized row tuples. */
export type SearchChunk = {
	version: number;
	entity: Entity;
	columns: string[];
	count: number;
	rows: SearchRow[];
};

/** Bounded jobs-board search response returned by the server route. */
export type JobsSearchResponse = SearchChunk & {
	entity: "jobs";
	totalMatches: number;
	limit: number;
	page: number;
	pageSize: number;
	totalPages: number;
	hasNextPage: boolean;
	hasPreviousPage: boolean;
	truncated: boolean;
};

export type JobsSearchSummaryResponse = {
	version: number;
	entity: "jobs";
	snapshotAt: string | null;
	totalMatches: number;
	sortKey: string;
	filtersHash: string;
};

export type SavedSearchCountQuery = {
	id: string;
	filters: import("@/components/jobs-board/jobs-board-filter-engine").JobBoardFilters;
	sortKey: import("@/components/jobs-board/jobs-board-filter-engine").JobSortKey;
	reviewedAt: string;
};

export type SavedSearchCountsResponse = {
	version: number;
	entity: "jobs";
	snapshotAt: string | null;
	semantics: "first-seen-v1";
	counts: Array<{
		id: string;
		totalMatches: number;
		newMatches: number;
	}>;
};

/** Job detail shard payload for preview sheets and deep links. */
export type JobDetail = {
	id: string;
	status?: string | null;
	sourceKey?: string | null;
	boardKey?: string | null;
	providerId?: string | null;
	remoteId?: string | null;
	title?: string | null;
	company?: string | null;
	department?: string | null;
	team?: string | null;
	workplaceType?: string | null;
	remote?: string | null;
	employmentType?: string | null;
	locations?: string[];
	salaryMin?: number | null;
	salaryMax?: number | null;
	salaryCurrency?: string | null;
	description?: string | null;
	responsibilities?: string[];
	qualifications?: string[];
	skills?: Array<{ name?: string; level?: string; keywords?: string[] }>;
	jobDescription?: Record<string, unknown> | null;
	compensation?: Record<string, unknown> | null;
	experience?: string | null;
	salary?: string | null;
	applyUrl?: string | null;
	postingUrl?: string | null;
	postedAt?: string | null;
	updatedAt?: string | null;
	versionCreatedAt?: string | null;
	firstSeenAt?: string | null;
	lastSeenAt?: string | null;
	closedAt?: string | null;
	syncedAt?: string | null;
	version?: number | null;
	contentHash?: string | null;
	payloadHash?: string | null;
	detailTier?: "T1" | "T2" | string | null;
	jobExtra?: Record<string, unknown> | null;
	versionExtra?: Record<string, unknown> | null;
};
