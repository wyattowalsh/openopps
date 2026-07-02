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
	};
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
};

/** Loaded entity chunk: column order plus materialized row tuples. */
export type SearchChunk = {
	version: number;
	entity: Entity;
	columns: string[];
	count: number;
	rows: SearchRow[];
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
	descriptionHtml?: string | null;
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
	jobExtra?: Record<string, unknown> | null;
	versionExtra?: Record<string, unknown> | null;
	payloadSnapshots?: Array<{
		kind?: string | null;
		payloadHash?: string | null;
		observedAt?: string | null;
		payload?: Record<string, unknown>;
		truncated?: boolean;
		originalChars?: number;
	}>;
};
