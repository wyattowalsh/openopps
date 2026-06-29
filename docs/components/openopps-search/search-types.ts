export type Entity = "jobs" | "boards" | "providers";
export type SearchRow = Array<string | number | null>;

export type SearchChunkRef = {
	index: number;
	path: string;
	file: string;
	count: number;
};

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

export type SearchManifest = {
	version: number;
	snapshotAt: string | null;
	openJobCount?: number;
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
	};
};

export type SearchChunk = {
	version: number;
	entity: Entity;
	columns: string[];
	count: number;
	rows: SearchRow[];
};

export type JobDetail = {
	id: string;
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
};
