import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	JobDetail,
	SearchRow,
} from "@/components/openopps-search/search-types";

export const JOBS_LOCAL_SCHEMA_VERSION = 1;
export const JOBS_LOCAL_SETTINGS_KEY = "openopps.jobs.local.settings.v1";
export const JOBS_LOCAL_DB_NAME = "openopps.jobs.local";
export const JOBS_LOCAL_DB_VERSION = 1;
export const JOBS_LOCAL_IMPORT_MAX_BYTES = 16 * 1024 * 1024;
export const JOBS_LOCAL_IMPORT_MAX_RECORDS = 5_000;

export type JobsRetentionMonths = 1 | 3 | 6 | 12 | "forever";
export type JobsLocalStorageStatus = "loading" | "available" | "unavailable" | "error";

export type JobsLocalSettings = {
	schemaVersion: typeof JOBS_LOCAL_SCHEMA_VERSION;
	fullDetailRetentionMonths: JobsRetentionMonths;
	showHidden: boolean;
	hideViewed: boolean;
	dismissedStorageNotice: boolean;
	lastRepairMessage?: string | null;
};

export type JobWorkflowRecord = {
	schemaVersion: typeof JOBS_LOCAL_SCHEMA_VERSION;
	jobId: string;
	createdAt: string;
	updatedAt: string;
	viewedAt: string | null;
	savedAt: string | null;
	hiddenAt: string | null;
	appliedAt: string | null;
	notes: string;
	firstSeenSnapshotAt: string | null;
	lastSeenSnapshotAt: string | null;
	firstAbsentSnapshotAt: string | null;
	lastKnownFingerprint: string | null;
	lastKnownTitle: string | null;
	lastKnownCompany: string | null;
};

export type RetainedJobDetailRecord = {
	schemaVersion: typeof JOBS_LOCAL_SCHEMA_VERSION;
	jobId: string;
	capturedAt: string;
	updatedAt: string;
	snapshotAt: string | null;
	rowSnapshot: SearchRow | null;
	detail: JobDetail;
};

export type SavedSearchRecord = {
	schemaVersion: typeof JOBS_LOCAL_SCHEMA_VERSION;
	id: string;
	label: string;
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	visibleColumns: string[];
	createdAt: string;
	updatedAt: string;
	lastOpenedAt: string | null;
	lastReviewedAt: string | null;
	manifestVersion: number | null;
	snapshotAt: string | null;
	baselineScope: "page" | "full";
	baselineTotalMatches: number | null;
	baseline: {
		reviewedJobIds: string[];
		reviewedFingerprints: Record<string, string>;
	};
};

export type JobsLocalSnapshot = {
	settings: JobsLocalSettings;
	jobRecords: JobWorkflowRecord[];
	savedSearches: SavedSearchRecord[];
	retainedJobDetails: RetainedJobDetailRecord[];
};

export type JobsLocalSummary = {
	viewed: number;
	saved: number;
	hidden: number;
	applied: number;
	noted: number;
	savedSearches: number;
	retainedDetails: number;
	staleDurableJobs: number;
	approximateBytes: number;
};

export type JobsLocalExportEnvelope = {
	source: "openopps.jobs.local";
	schemaVersion: typeof JOBS_LOCAL_SCHEMA_VERSION;
	exportedAt: string;
	settings: JobsLocalSettings;
	jobRecords: JobWorkflowRecord[];
	savedSearches: SavedSearchRecord[];
	retainedJobDetails: RetainedJobDetailRecord[];
};

export type JobsLocalReconciliationResult = {
	jobRecords: JobWorkflowRecord[];
	retainedJobDetails: RetainedJobDetailRecord[];
	prunedRetainedJobIds: string[];
};

export type JobLifecycleIndicator = "changed" | "new" | "stale";

export type JobLifecycleBaseline = {
	reviewedJobIds: ReadonlySet<string>;
	reviewedFingerprints: Record<string, string>;
};

export type JobsLocalIndexedSnapshot = Omit<JobsLocalSnapshot, "settings">;

export const DEFAULT_JOBS_LOCAL_SETTINGS: JobsLocalSettings = {
	schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
	fullDetailRetentionMonths: 6,
	showHidden: false,
	hideViewed: false,
	dismissedStorageNotice: false,
	lastRepairMessage: null,
};

export const RETENTION_VALUES = new Set<JobsRetentionMonths>([1, 3, 6, 12, "forever"]);