"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	JobDetail,
	JobsSearchSummaryResponse,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";
import { safeJobExternalUrl } from "@/lib/job-url";

export const JOBS_LOCAL_SCHEMA_VERSION = 1;
export const JOBS_LOCAL_SETTINGS_KEY = "openopps.jobs.local.settings.v1";
export const JOBS_LOCAL_DB_NAME = "openopps.jobs.local";
export const JOBS_LOCAL_DB_VERSION = 1;
export const JOBS_LOCAL_IMPORT_MAX_BYTES = 16 * 1024 * 1024;
export const JOBS_LOCAL_IMPORT_MAX_RECORDS = 5_000;

const JOB_RECORD_STORE = "jobRecords";
const SAVED_SEARCH_STORE = "savedSearches";
const RETAINED_DETAIL_STORE = "retainedJobDetails";

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

type JobsLocalIndexedSnapshot = Omit<JobsLocalSnapshot, "settings">;
type KeyValueStorage = Pick<Storage, "getItem" | "removeItem" | "setItem">;

export const DEFAULT_JOBS_LOCAL_SETTINGS: JobsLocalSettings = {
	schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
	fullDetailRetentionMonths: 6,
	showHidden: false,
	hideViewed: false,
	dismissedStorageNotice: false,
	lastRepairMessage: null,
};

const RETENTION_VALUES = new Set<JobsRetentionMonths>([1, 3, 6, 12, "forever"]);

let dbPromise: Promise<IDBDatabase | null> | null = null;

export function createEmptyJobsLocalSnapshot(
	settings: JobsLocalSettings = DEFAULT_JOBS_LOCAL_SETTINGS,
): JobsLocalSnapshot {
	return {
		settings,
		jobRecords: [],
		savedSearches: [],
		retainedJobDetails: [],
	};
}

export function normalizeJobsLocalSettings(value: unknown): JobsLocalSettings {
	if (!value || typeof value !== "object") {
		return { ...DEFAULT_JOBS_LOCAL_SETTINGS };
	}
	const candidate = value as Partial<JobsLocalSettings>;
	const retention = RETENTION_VALUES.has(
		candidate.fullDetailRetentionMonths as JobsRetentionMonths,
	)
		? (candidate.fullDetailRetentionMonths as JobsRetentionMonths)
		: DEFAULT_JOBS_LOCAL_SETTINGS.fullDetailRetentionMonths;
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		fullDetailRetentionMonths: retention,
		showHidden: Boolean(candidate.showHidden),
		hideViewed: Boolean(candidate.hideViewed),
		dismissedStorageNotice: Boolean(candidate.dismissedStorageNotice),
		lastRepairMessage:
			typeof candidate.lastRepairMessage === "string"
				? candidate.lastRepairMessage
				: null,
	};
}

function mergeJobsLocalSettings(
	current: JobsLocalSettings,
	incoming: JobsLocalSettings,
): JobsLocalSettings {
	const currentSettings = normalizeJobsLocalSettings(current);
	const incomingSettings = normalizeJobsLocalSettings(incoming);
	return normalizeJobsLocalSettings({
		fullDetailRetentionMonths: currentSettings.fullDetailRetentionMonths,
		showHidden: currentSettings.showHidden || incomingSettings.showHidden,
		hideViewed: currentSettings.hideViewed || incomingSettings.hideViewed,
		dismissedStorageNotice:
			currentSettings.dismissedStorageNotice || incomingSettings.dismissedStorageNotice,
		lastRepairMessage:
			currentSettings.lastRepairMessage ?? incomingSettings.lastRepairMessage ?? null,
	});
}

export function readJobsLocalSettings(
	storage: KeyValueStorage | undefined = browserLocalStorage(),
): JobsLocalSettings {
	if (!storage) {
		return { ...DEFAULT_JOBS_LOCAL_SETTINGS };
	}
	const raw = storage.getItem(JOBS_LOCAL_SETTINGS_KEY);
	if (!raw) {
		return { ...DEFAULT_JOBS_LOCAL_SETTINGS };
	}
	try {
		return normalizeJobsLocalSettings(JSON.parse(raw));
	} catch {
		return {
			...DEFAULT_JOBS_LOCAL_SETTINGS,
			lastRepairMessage: "Local settings were reset because the saved JSON was invalid.",
		};
	}
}

export function writeJobsLocalSettings(
	settings: JobsLocalSettings,
	storage: KeyValueStorage | undefined = browserLocalStorage(),
) {
	if (!storage) {
		return;
	}
	storage.setItem(
		JOBS_LOCAL_SETTINGS_KEY,
		JSON.stringify(normalizeJobsLocalSettings(settings)),
	);
}

export function removeJobsLocalSettings(
	storage: KeyValueStorage | undefined = browserLocalStorage(),
) {
	storage?.removeItem(JOBS_LOCAL_SETTINGS_KEY);
}

export function createJobWorkflowRecord({
	jobId,
	now,
	snapshotAt,
	row,
}: {
	jobId: string;
	now: string;
	snapshotAt?: string | null;
	row?: SearchRow | null;
}): JobWorkflowRecord {
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		jobId,
		createdAt: now,
		updatedAt: now,
		viewedAt: null,
		savedAt: null,
		hiddenAt: null,
		appliedAt: null,
		notes: "",
		firstSeenSnapshotAt: snapshotAt ?? null,
		lastSeenSnapshotAt: snapshotAt ?? null,
		firstAbsentSnapshotAt: null,
		lastKnownFingerprint: row ? jobFingerprint(row) : null,
		lastKnownTitle: row ? text(row[J.title]) || null : null,
		lastKnownCompany: row ? text(row[J.company]) || text(row[J.board]) || null : null,
	};
}

export function normalizeJobWorkflowRecord(
	value: unknown,
	now = new Date().toISOString(),
): JobWorkflowRecord | null {
	if (!value || typeof value !== "object") {
		return null;
	}
	const candidate = value as Partial<JobWorkflowRecord>;
	const jobId = typeof candidate.jobId === "string" ? candidate.jobId.trim() : "";
	if (!jobId) {
		return null;
	}
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		jobId,
		createdAt: stringOr(candidate.createdAt, now),
		updatedAt: stringOr(candidate.updatedAt, now),
		viewedAt: nullableString(candidate.viewedAt),
		savedAt: nullableString(candidate.savedAt),
		hiddenAt: nullableString(candidate.hiddenAt),
		appliedAt: nullableString(candidate.appliedAt),
		notes: typeof candidate.notes === "string" ? candidate.notes : "",
		firstSeenSnapshotAt: nullableString(candidate.firstSeenSnapshotAt),
		lastSeenSnapshotAt: nullableString(candidate.lastSeenSnapshotAt),
		firstAbsentSnapshotAt: nullableString(candidate.firstAbsentSnapshotAt),
		lastKnownFingerprint: nullableString(candidate.lastKnownFingerprint),
		lastKnownTitle: nullableString(candidate.lastKnownTitle),
		lastKnownCompany: nullableString(candidate.lastKnownCompany),
	};
}

export function normalizeSavedSearchRecord(
	value: unknown,
	now = new Date().toISOString(),
): SavedSearchRecord | null {
	if (!value || typeof value !== "object") {
		return null;
	}
	const candidate = value as Partial<SavedSearchRecord>;
	const id = typeof candidate.id === "string" ? candidate.id.trim() : "";
	if (!id || !candidate.filters || typeof candidate.filters !== "object") {
		return null;
	}
	const baselineScope = candidate.baselineScope === "full" ? "full" : "page";
	const reviewedJobIds = Array.isArray(candidate.baseline?.reviewedJobIds)
		? candidate.baseline.reviewedJobIds.map(text).filter(Boolean)
		: [];
	const reviewedFingerprints =
		candidate.baseline?.reviewedFingerprints &&
		typeof candidate.baseline.reviewedFingerprints === "object"
			? Object.fromEntries(
					Object.entries(candidate.baseline.reviewedFingerprints)
						.map(([key, value]) => [key, text(value)])
						.filter(([key, value]) => key && value),
				)
			: {};
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		id,
		label: stringOr(candidate.label, "Saved search"),
		filters: candidate.filters as JobBoardFilters,
		sortKey: candidate.sortKey === "relevance" ? "relevance" : "latest",
		visibleColumns: Array.isArray(candidate.visibleColumns)
			? candidate.visibleColumns.map(text).filter(Boolean)
			: [],
		createdAt: stringOr(candidate.createdAt, now),
		updatedAt: stringOr(candidate.updatedAt, now),
		lastOpenedAt: nullableString(candidate.lastOpenedAt),
		lastReviewedAt: nullableString(candidate.lastReviewedAt),
		manifestVersion:
			typeof candidate.manifestVersion === "number"
				? candidate.manifestVersion
				: null,
		snapshotAt: nullableString(candidate.snapshotAt),
		baselineScope,
		baselineTotalMatches:
			typeof candidate.baselineTotalMatches === "number" &&
			Number.isFinite(candidate.baselineTotalMatches)
				? Math.max(0, Math.trunc(candidate.baselineTotalMatches))
				: baselineScope === "full"
					? reviewedJobIds.length
					: null,
		baseline: {
			reviewedJobIds,
			reviewedFingerprints,
		},
	};
}

export function normalizeRetainedJobDetailRecord(
	value: unknown,
	now = new Date().toISOString(),
): RetainedJobDetailRecord | null {
	if (!value || typeof value !== "object") {
		return null;
	}
	const candidate = value as Partial<RetainedJobDetailRecord>;
	const jobId = typeof candidate.jobId === "string" ? candidate.jobId.trim() : "";
	if (!jobId || !candidate.detail || typeof candidate.detail !== "object") {
		return null;
	}
	const detail = sanitizeRetainedJobDetail(candidate.detail as JobDetail);
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		jobId,
		capturedAt: stringOr(candidate.capturedAt, now),
		updatedAt: stringOr(candidate.updatedAt, now),
		snapshotAt: nullableString(candidate.snapshotAt),
		rowSnapshot: Array.isArray(candidate.rowSnapshot)
			? (candidate.rowSnapshot as SearchRow)
			: null,
		detail,
	};
}

function sanitizeRetainedJobDetail(detail: JobDetail): JobDetail {
	const retained = detail as JobDetail & {
		descriptionHtml?: unknown;
		payloadSnapshots?: unknown;
	};
	const legacyHtmlDescription =
		typeof retained.descriptionHtml === "string"
			? stripTags(retained.descriptionHtml)
			: "";
	const { descriptionHtml, payloadSnapshots, ...publicDetail } = retained;
	void descriptionHtml;
	void payloadSnapshots;
	return {
		...publicDetail,
		postingUrl: safeJobExternalUrl(detail.postingUrl),
		applyUrl: safeJobExternalUrl(detail.applyUrl),
		description: text(detail.description) || legacyHtmlDescription || null,
	};
}

function stripTags(value: string) {
	return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

export function updateJobWorkflowRecord(
	record: JobWorkflowRecord | null,
	patch: Partial<
		Pick<JobWorkflowRecord, "appliedAt" | "hiddenAt" | "notes" | "savedAt" | "viewedAt">
	>,
	context: {
		jobId: string;
		now: string;
		snapshotAt?: string | null;
		row?: SearchRow | null;
	},
) {
	const base =
		record ??
		createJobWorkflowRecord({
			jobId: context.jobId,
			now: context.now,
			snapshotAt: context.snapshotAt ?? null,
			row: context.row ?? null,
		});
	const fingerprint = context.row ? jobFingerprint(context.row) : base.lastKnownFingerprint;
	return {
		...base,
		...patch,
		updatedAt: context.now,
		lastSeenSnapshotAt: context.snapshotAt ?? base.lastSeenSnapshotAt,
		firstAbsentSnapshotAt: context.row ? null : base.firstAbsentSnapshotAt,
		lastKnownFingerprint: fingerprint,
		lastKnownTitle: context.row
			? text(context.row[J.title]) || base.lastKnownTitle
			: base.lastKnownTitle,
		lastKnownCompany: context.row
			? text(context.row[J.company]) || text(context.row[J.board]) || base.lastKnownCompany
			: base.lastKnownCompany,
	} satisfies JobWorkflowRecord;
}

export function isDurableJobWorkflowRecord(record: JobWorkflowRecord | null | undefined) {
	return Boolean(
		record?.viewedAt ||
			record?.savedAt ||
			record?.hiddenAt ||
			record?.appliedAt ||
			(record?.notes ?? "").trim(),
	);
}

export function shouldRetainJobDetail(record: JobWorkflowRecord | null | undefined) {
	return Boolean(
		record?.savedAt ||
			record?.hiddenAt ||
			record?.appliedAt ||
			(record?.notes ?? "").trim(),
	);
}

export function jobFingerprint(row: SearchRow) {
	const hashFingerprint = [
		text(row[J.contentHash]),
		text(row[J.payloadHash]),
	].filter(Boolean);
	if (hashFingerprint.length) {
		return hashFingerprint.join("|");
	}
	return [
		text(row[J.id]),
		text(row[J.latestObserved]),
		text(row[J.syncedAt]),
		text(row[J.title]),
		text(row[J.company]),
		text(row[J.descriptionSnippet]),
	]
		.filter(Boolean)
		.join("|");
}

export function createRetainedJobDetailRecord({
	row,
	detail,
	now,
	snapshotAt,
}: {
	row: SearchRow | null;
	detail: JobDetail;
	now: string;
	snapshotAt?: string | null;
}): RetainedJobDetailRecord {
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		jobId: detail.id,
		capturedAt: now,
		updatedAt: now,
		snapshotAt: snapshotAt ?? null,
		rowSnapshot: row,
		detail,
	};
}

export function createSavedSearchRecord({
	filters,
	rows,
	baseline,
	baselineScope = "page",
	baselineTotalMatches,
	label,
	sortKey,
	manifest,
	now,
}: {
	filters: JobBoardFilters;
	rows: SearchRow[];
	baseline?: SavedSearchRecord["baseline"];
	baselineScope?: SavedSearchRecord["baselineScope"];
	baselineTotalMatches?: number | null;
	label?: string;
	sortKey: JobSortKey;
	manifest: SearchManifest | null;
	now: string;
}): SavedSearchRecord {
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		id: createLocalId("search", now),
		label: label?.trim() || defaultSavedSearchLabel(filters),
		filters,
		sortKey,
		visibleColumns: [],
		createdAt: now,
		updatedAt: now,
		lastOpenedAt: null,
		lastReviewedAt: now,
		manifestVersion: manifest?.version ?? null,
		snapshotAt: manifest?.snapshotAt ?? null,
		baselineScope,
		baselineTotalMatches:
			baselineScope === "full"
				? baselineTotalMatches ?? baseline?.reviewedJobIds.length ?? rows.length
				: baselineTotalMatches ?? null,
		baseline: baseline ?? baselineFromRows(rows),
	};
}

export function duplicateSavedSearchRecord(
	record: SavedSearchRecord,
	now = new Date().toISOString(),
) {
	return {
		...record,
		id: createLocalId("search", now),
		label: `${record.label} copy`,
		createdAt: now,
		updatedAt: now,
		lastOpenedAt: null,
	} satisfies SavedSearchRecord;
}

export function savedSearchNewMatchCount(record: SavedSearchRecord, rows: SearchRow[]) {
	const reviewedIds = new Set(record.baseline.reviewedJobIds);
	let count = 0;
	for (const row of rows) {
		const jobId = text(row[J.id]);
		if (!jobId) {
			continue;
		}
		const previousFingerprint = record.baseline.reviewedFingerprints[jobId];
		if (!reviewedIds.has(jobId) || previousFingerprint !== jobFingerprint(row)) {
			count += 1;
		}
	}
	return count;
}

export function savedSearchNewMatchCountFromSummary(
	record: SavedSearchRecord,
	summary: JobsSearchSummaryResponse,
) {
	const reviewedIds = new Set(record.baseline.reviewedJobIds);
	let count = 0;
	for (const entry of summary.entries) {
		if (!entry.id) {
			continue;
		}
		const previousFingerprint = record.baseline.reviewedFingerprints[entry.id];
		if (!reviewedIds.has(entry.id) || previousFingerprint !== entry.fingerprint) {
			count += 1;
		}
	}
	return count;
}

export function baselineFromRows(rows: SearchRow[]) {
	return {
		reviewedJobIds: rows.map((row) => text(row[J.id])).filter(Boolean),
		reviewedFingerprints: Object.fromEntries(
			rows
				.map((row) => [text(row[J.id]), jobFingerprint(row)] as const)
				.filter(([jobId]) => Boolean(jobId)),
		),
	};
}

export function baselineFromSearchSummary(summary: JobsSearchSummaryResponse) {
	return {
		reviewedJobIds: summary.entries.map((entry) => text(entry.id)).filter(Boolean),
		reviewedFingerprints: Object.fromEntries(
			summary.entries
				.map((entry) => [text(entry.id), text(entry.fingerprint)] as const)
				.filter(([jobId, fingerprint]) => Boolean(jobId && fingerprint)),
		),
	};
}

export function baselineLookupFromSavedSearch(
	record: SavedSearchRecord | null | undefined,
): JobLifecycleBaseline | null {
	if (!record) {
		return null;
	}
	return {
		reviewedJobIds: new Set(record.baseline.reviewedJobIds),
		reviewedFingerprints: record.baseline.reviewedFingerprints,
	};
}

export function jobLifecycleIndicators({
	row,
	workflowRecord,
	baseline,
}: {
	row: SearchRow;
	workflowRecord?: JobWorkflowRecord | null;
	baseline?: JobLifecycleBaseline | null;
}): JobLifecycleIndicator[] {
	const jobId = text(row[J.id]);
	const currentFingerprint = jobFingerprint(row);
	const indicators: JobLifecycleIndicator[] = [];

	if (baseline && jobId) {
		const previousFingerprint = baseline.reviewedFingerprints[jobId];
		if (!baseline.reviewedJobIds.has(jobId)) {
			indicators.push("new");
		} else if (previousFingerprint && previousFingerprint !== currentFingerprint) {
			indicators.push("changed");
		}
	} else if (
		workflowRecord?.lastKnownFingerprint &&
		workflowRecord.lastKnownFingerprint !== currentFingerprint
	) {
		indicators.push("changed");
	}

	const status = text(row[J.status]).toLowerCase();
	if (workflowRecord?.firstAbsentSnapshotAt || (status && status !== "open")) {
		indicators.push("stale");
	}

	return indicators;
}

export function reconcileJobsLocalSnapshot({
	snapshot,
	rows,
	manifest,
	now = new Date().toISOString(),
}: {
	snapshot: JobsLocalSnapshot;
	rows: SearchRow[];
	manifest: SearchManifest | null;
	now?: string;
}): JobsLocalReconciliationResult {
	const snapshotAt = manifest?.snapshotAt ?? now;
	const rowsById = new Map(
		rows
			.map((row) => [text(row[J.id]), row] as const)
			.filter(([jobId]) => Boolean(jobId)),
	);
	const nextRecords = snapshot.jobRecords.map((record) => {
		const row = rowsById.get(record.jobId);
		if (row) {
			return updateJobWorkflowRecord(
				record,
				{},
				{ jobId: record.jobId, now, row, snapshotAt },
			);
		}
		if (!isDurableJobWorkflowRecord(record)) {
			return record;
		}
		return {
			...record,
			updatedAt: record.firstAbsentSnapshotAt ? record.updatedAt : now,
			firstAbsentSnapshotAt: record.firstAbsentSnapshotAt ?? snapshotAt,
		} satisfies JobWorkflowRecord;
	});
	const recordsById = indexByJobId(nextRecords);
	const retainedJobDetails: RetainedJobDetailRecord[] = [];
	const prunedRetainedJobIds: string[] = [];
	for (const retained of snapshot.retainedJobDetails) {
		const record = recordsById[retained.jobId];
		if (
			!shouldRetainJobDetail(record) ||
			(record?.firstAbsentSnapshotAt &&
				shouldPruneRetainedDetail(
					record.firstAbsentSnapshotAt,
					snapshot.settings.fullDetailRetentionMonths,
					now,
				))
		) {
			prunedRetainedJobIds.push(retained.jobId);
			continue;
		}
		retainedJobDetails.push(retained);
	}
	return {
		jobRecords: nextRecords,
		retainedJobDetails,
		prunedRetainedJobIds,
	};
}

export function pruneRetainedJobDetailsForWorkflowRecords({
	jobRecords,
	retainedJobDetails,
}: {
	jobRecords: Record<string, JobWorkflowRecord>;
	retainedJobDetails: Record<string, RetainedJobDetailRecord>;
}) {
	const retained: Record<string, RetainedJobDetailRecord> = {};
	const prunedJobIds: string[] = [];
	for (const [jobId, detail] of Object.entries(retainedJobDetails)) {
		if (shouldRetainJobDetail(jobRecords[jobId])) {
			retained[jobId] = detail;
		} else {
			prunedJobIds.push(jobId);
		}
	}
	return { retained, prunedJobIds };
}

export function mergeJobsLocalSnapshots(
	current: JobsLocalSnapshot,
	incoming: JobsLocalSnapshot,
): JobsLocalSnapshot {
	return {
		settings: mergeJobsLocalSettings(current.settings, incoming.settings),
		jobRecords: Object.values(
			mergeByUpdatedAt(indexByJobId(current.jobRecords), incoming.jobRecords),
		),
		savedSearches: Object.values(
			mergeById(indexById(current.savedSearches), incoming.savedSearches),
		),
		retainedJobDetails: Object.values(
			mergeByUpdatedAt(
				indexByJobId(current.retainedJobDetails),
				incoming.retainedJobDetails,
			),
		),
	};
}

export function summarizeJobsLocalData(snapshot: JobsLocalSnapshot): JobsLocalSummary {
	const currentJobIds = new Set(snapshot.jobRecords.map((record) => record.jobId));
	const staleDurableJobs = snapshot.jobRecords.filter(
		(record) => isDurableJobWorkflowRecord(record) && record.firstAbsentSnapshotAt,
	).length;
	return {
		viewed: snapshot.jobRecords.filter((record) => record.viewedAt).length,
		saved: snapshot.jobRecords.filter((record) => record.savedAt).length,
		hidden: snapshot.jobRecords.filter((record) => record.hiddenAt).length,
		applied: snapshot.jobRecords.filter((record) => record.appliedAt).length,
		noted: snapshot.jobRecords.filter((record) => record.notes.trim()).length,
		savedSearches: snapshot.savedSearches.length,
		retainedDetails: snapshot.retainedJobDetails.length,
		staleDurableJobs,
		approximateBytes: approximateJsonBytes({
			...snapshot,
			retainedJobDetails: snapshot.retainedJobDetails.filter((detail) =>
				currentJobIds.has(detail.jobId),
			),
		}),
	};
}

export function createJobsLocalExportEnvelope(
	snapshot: JobsLocalSnapshot,
	now = new Date().toISOString(),
): JobsLocalExportEnvelope {
	return {
		source: "openopps.jobs.local",
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		exportedAt: now,
		settings: normalizeJobsLocalSettings(snapshot.settings),
		jobRecords: snapshot.jobRecords
			.map((record) => normalizeJobWorkflowRecord(record, now))
			.filter(isPresent),
		savedSearches: snapshot.savedSearches
			.map((record) => normalizeSavedSearchRecord(record, now))
			.filter(isPresent),
		retainedJobDetails: snapshot.retainedJobDetails
			.map((record) => normalizeRetainedJobDetailRecord(record, now))
			.filter(isPresent),
	};
}

export function parseJobsLocalImport(value: string | unknown):
	| { ok: true; data: JobsLocalExportEnvelope }
	| { ok: false; errors: string[] } {
	if (typeof value === "string") {
		const byteLength = new TextEncoder().encode(value).length;
		if (byteLength > JOBS_LOCAL_IMPORT_MAX_BYTES) {
			return {
				ok: false,
				errors: [
					`Import file exceeds the ${formatImportLimit(JOBS_LOCAL_IMPORT_MAX_BYTES)} size limit.`,
				],
			};
		}
	}
	let parsed: unknown = value;
	if (typeof value === "string") {
		try {
			parsed = JSON.parse(value);
		} catch {
			return { ok: false, errors: ["Import file is not valid JSON."] };
		}
	}
	if (!parsed || typeof parsed !== "object") {
		return { ok: false, errors: ["Import payload must be an object."] };
	}
	const candidate = parsed as Partial<JobsLocalExportEnvelope>;
	if (
		candidate.source !== "openopps.jobs.local" ||
		candidate.schemaVersion !== JOBS_LOCAL_SCHEMA_VERSION
	) {
		return {
			ok: false,
			errors: ["Import payload is not an OpenOpps jobs local data backup."],
		};
	}
	const recordCount =
		(Array.isArray(candidate.jobRecords) ? candidate.jobRecords.length : 0) +
		(Array.isArray(candidate.savedSearches) ? candidate.savedSearches.length : 0) +
		(Array.isArray(candidate.retainedJobDetails)
			? candidate.retainedJobDetails.length
			: 0);
	if (recordCount > JOBS_LOCAL_IMPORT_MAX_RECORDS) {
		return {
			ok: false,
			errors: [
				`Import payload exceeds the ${JOBS_LOCAL_IMPORT_MAX_RECORDS.toLocaleString()} record limit.`,
			],
		};
	}
	const now = new Date().toISOString();
	return {
		ok: true,
		data: {
			source: "openopps.jobs.local",
			schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
			exportedAt: stringOr(candidate.exportedAt, now),
			settings: normalizeJobsLocalSettings(candidate.settings),
			jobRecords: Array.isArray(candidate.jobRecords)
				? candidate.jobRecords
						.map((record) => normalizeJobWorkflowRecord(record, now))
						.filter(isPresent)
				: [],
			savedSearches: Array.isArray(candidate.savedSearches)
				? candidate.savedSearches
						.map((record) => normalizeSavedSearchRecord(record, now))
						.filter(isPresent)
				: [],
			retainedJobDetails: Array.isArray(candidate.retainedJobDetails)
				? candidate.retainedJobDetails
						.map((record) => normalizeRetainedJobDetailRecord(record, now))
						.filter(isPresent)
				: [],
		},
	};
}

export function useJobsLocalState() {
	const [settings, setSettingsState] = useState<JobsLocalSettings>(() =>
		readJobsLocalSettings(),
	);
	const [jobRecords, setJobRecords] = useState<Record<string, JobWorkflowRecord>>({});
	const [savedSearches, setSavedSearches] = useState<SavedSearchRecord[]>([]);
	const [retainedJobDetails, setRetainedJobDetails] = useState<
		Record<string, RetainedJobDetailRecord>
	>({});
	const [storageStatus, setStorageStatus] =
		useState<JobsLocalStorageStatus>("loading");

	useEffect(() => {
		let mounted = true;
		async function load() {
			try {
				const snapshot = await readIndexedJobsLocalSnapshot();
				if (!mounted) {
					return;
				}
				setJobRecords(indexByJobId(snapshot.jobRecords));
				setSavedSearches(snapshot.savedSearches);
				setRetainedJobDetails(indexByJobId(snapshot.retainedJobDetails));
				setStorageStatus(hasBrowserIndexedDb() ? "available" : "unavailable");
			} catch {
				if (mounted) {
					setStorageStatus("error");
				}
			}
		}
		void load();
		return () => {
			mounted = false;
		};
	}, []);

	const setSettings = useCallback((patch: Partial<JobsLocalSettings>) => {
		setSettingsState((current) => {
			const next = normalizeJobsLocalSettings({ ...current, ...patch });
			writeJobsLocalSettings(next);
			return next;
		});
	}, []);

	const upsertJobRecord = useCallback(
		(
			jobId: string,
			updater: (record: JobWorkflowRecord | null, now: string) => JobWorkflowRecord,
			options: {
				row?: SearchRow | null;
				detail?: JobDetail | null;
				snapshotAt?: string | null;
			} = {},
		) => {
			const normalizedJobId = jobId.trim();
			if (!normalizedJobId) {
				return;
			}
			const now = new Date().toISOString();
			setJobRecords((current) => {
				const nextRecord = updater(current[normalizedJobId] ?? null, now);
				void writeStoreRecord(JOB_RECORD_STORE, nextRecord);
				if (
					options.detail &&
					options.detail.id === normalizedJobId &&
					shouldRetainJobDetail(nextRecord)
				) {
					const retained = createRetainedJobDetailRecord({
						row: options.row ?? null,
						detail: options.detail,
						now,
						snapshotAt: options.snapshotAt ?? null,
					});
					void writeStoreRecord(RETAINED_DETAIL_STORE, retained);
					setRetainedJobDetails((details) => ({
						...details,
						[normalizedJobId]: retained,
					}));
				} else if (!shouldRetainJobDetail(nextRecord)) {
					void deleteStoreRecord(RETAINED_DETAIL_STORE, normalizedJobId);
					setRetainedJobDetails((details) => {
						if (!(normalizedJobId in details)) {
							return details;
						}
						const next = { ...details };
						delete next[normalizedJobId];
						return next;
					});
				}
				return { ...current, [normalizedJobId]: nextRecord };
			});
		},
		[],
	);

	const markViewed = useCallback(
		(jobId: string, row: SearchRow | null, snapshotAt: string | null) => {
			upsertJobRecord(jobId, (record, now) => {
				if (record?.viewedAt) {
					return updateJobWorkflowRecord(record, {}, { jobId, now, row, snapshotAt });
				}
				return updateJobWorkflowRecord(
					record,
					{ viewedAt: now },
					{ jobId, now, row, snapshotAt },
				);
			});
		},
		[upsertJobRecord],
	);

	const toggleJobFlag = useCallback(
		(
			jobId: string,
			flag: "appliedAt" | "hiddenAt" | "savedAt",
			options: {
				row?: SearchRow | null;
				detail?: JobDetail | null;
				snapshotAt?: string | null;
			} = {},
		) => {
			upsertJobRecord(
				jobId,
				(record, now) =>
					updateJobWorkflowRecord(
						record,
						{ [flag]: record?.[flag] ? null : now },
						{
							jobId,
							now,
							row: options.row ?? null,
							snapshotAt: options.snapshotAt ?? null,
						},
					),
				options,
			);
		},
		[upsertJobRecord],
	);

	const updateNotes = useCallback(
		(
			jobId: string,
			notes: string,
			options: {
				row?: SearchRow | null;
				detail?: JobDetail | null;
				snapshotAt?: string | null;
			} = {},
		) => {
			upsertJobRecord(
				jobId,
				(record, now) =>
					updateJobWorkflowRecord(
						record,
						{ notes },
						{
							jobId,
							now,
							row: options.row ?? null,
							snapshotAt: options.snapshotAt ?? null,
						},
					),
				options,
			);
		},
		[upsertJobRecord],
	);

	const retainJobDetail = useCallback(
		(jobId: string, row: SearchRow | null, detail: JobDetail, snapshotAt: string | null) => {
			const normalizedJobId = jobId.trim();
				if (!normalizedJobId || detail.id !== normalizedJobId) {
					return;
				}
				const record = jobRecords[normalizedJobId];
				if (!shouldRetainJobDetail(record)) {
					return;
				}
			const now = new Date().toISOString();
			const retained = createRetainedJobDetailRecord({
				row,
				detail,
				now,
				snapshotAt,
			});
			setRetainedJobDetails((current) => ({
				...current,
				[normalizedJobId]: retained,
			}));
			void writeStoreRecord(RETAINED_DETAIL_STORE, retained);
		},
		[jobRecords],
	);

	const createSavedSearch = useCallback(
		({
			filters,
				rows,
				baseline,
				baselineScope,
				baselineTotalMatches,
				sortKey,
				manifest,
			}: {
				filters: JobBoardFilters;
				rows: SearchRow[];
				baseline?: SavedSearchRecord["baseline"];
				baselineScope?: SavedSearchRecord["baselineScope"];
				baselineTotalMatches?: number | null;
				sortKey: JobSortKey;
				manifest: SearchManifest | null;
			}) => {
			const now = new Date().toISOString();
			const record = createSavedSearchRecord({
					filters,
					rows,
					baseline,
					baselineScope,
					baselineTotalMatches,
					sortKey,
					manifest,
					now,
			});
			setSavedSearches((current) => [...current, record]);
			void writeStoreRecord(SAVED_SEARCH_STORE, record);
		},
		[],
	);

	const updateSavedSearch = useCallback((record: SavedSearchRecord) => {
		const next = { ...record, updatedAt: new Date().toISOString() };
		setSavedSearches((current) =>
			current.map((candidate) => (candidate.id === next.id ? next : candidate)),
		);
		void writeStoreRecord(SAVED_SEARCH_STORE, next);
	}, []);

	const deleteSavedSearch = useCallback((id: string) => {
		setSavedSearches((current) => current.filter((record) => record.id !== id));
		void deleteStoreRecord(SAVED_SEARCH_STORE, id);
	}, []);

	const duplicateSavedSearch = useCallback((record: SavedSearchRecord) => {
		const duplicate = duplicateSavedSearchRecord(record);
		setSavedSearches((current) => [...current, duplicate]);
		void writeStoreRecord(SAVED_SEARCH_STORE, duplicate);
	}, []);

	const markSavedSearchReviewed = useCallback(
		(
			record: SavedSearchRecord,
			rows: SearchRow[],
			manifest: SearchManifest | null,
			options: {
				baseline?: SavedSearchRecord["baseline"];
				baselineScope?: SavedSearchRecord["baselineScope"];
				baselineTotalMatches?: number | null;
			} = {},
		) => {
			const now = new Date().toISOString();
			updateSavedSearch({
				...record,
				lastReviewedAt: now,
				lastOpenedAt: now,
				manifestVersion: manifest?.version ?? record.manifestVersion,
				snapshotAt: manifest?.snapshotAt ?? record.snapshotAt,
				baselineScope: options.baselineScope ?? "page",
				baselineTotalMatches:
					options.baselineScope === "full"
						? options.baselineTotalMatches ??
							options.baseline?.reviewedJobIds.length ??
							rows.length
						: options.baselineTotalMatches ?? null,
				baseline: options.baseline ?? baselineFromRows(rows),
			});
		},
		[updateSavedSearch],
	);

	const clearCategory = useCallback(
		async (
			category:
				| "all"
				| "applied"
				| "details"
				| "hidden"
				| "notes"
				| "saved"
				| "savedSearches"
				| "viewed",
		) => {
			if (category === "all") {
				removeJobsLocalSettings();
				const nextSettings = { ...DEFAULT_JOBS_LOCAL_SETTINGS };
				setSettingsState(nextSettings);
				setJobRecords({});
				setSavedSearches([]);
				setRetainedJobDetails({});
				await clearIndexedJobsLocalData();
				return;
			}
			if (category === "savedSearches") {
				setSavedSearches([]);
				await clearStore(SAVED_SEARCH_STORE);
				return;
			}
			if (category === "details") {
				setRetainedJobDetails({});
				await clearStore(RETAINED_DETAIL_STORE);
				return;
			}
				setJobRecords((current) => {
					const now = new Date().toISOString();
					const next: Record<string, JobWorkflowRecord> = {};
					for (const [jobId, record] of Object.entries(current)) {
						const patch = clearPatchForCategory(category);
						const nextRecord = updateJobWorkflowRecord(record, patch, { jobId, now });
						next[jobId] = nextRecord;
						void writeStoreRecord(JOB_RECORD_STORE, nextRecord);
					}
					const pruned = pruneRetainedJobDetailsForWorkflowRecords({
						jobRecords: next,
						retainedJobDetails,
					});
					if (pruned.prunedJobIds.length > 0) {
						setRetainedJobDetails(pruned.retained);
						for (const jobId of pruned.prunedJobIds) {
							void deleteStoreRecord(RETAINED_DETAIL_STORE, jobId);
						}
					}
					return next;
				});
			},
			[retainedJobDetails],
		);

	const exportLocalData = useCallback(() => {
		const snapshot: JobsLocalSnapshot = {
			settings,
			jobRecords: Object.values(jobRecords),
			savedSearches,
			retainedJobDetails: Object.values(retainedJobDetails),
		};
		return JSON.stringify(createJobsLocalExportEnvelope(snapshot), null, 2);
	}, [jobRecords, retainedJobDetails, savedSearches, settings]);

	const importLocalData = useCallback(async (raw: string, mode: "merge" | "replace") => {
		const parsed = parseJobsLocalImport(raw);
		if (!parsed.ok) {
			return parsed;
		}
		const currentSnapshot: JobsLocalSnapshot = {
			settings,
			jobRecords: Object.values(jobRecords),
			savedSearches,
			retainedJobDetails: Object.values(retainedJobDetails),
		};
		const nextSnapshot =
			mode === "replace"
				? parsed.data
				: mergeJobsLocalSnapshots(currentSnapshot, parsed.data);
		if (mode === "replace") {
			await clearIndexedJobsLocalData();
		}
		writeJobsLocalSettings(nextSnapshot.settings);
		setSettingsState(nextSnapshot.settings);
		setJobRecords(indexByJobId(nextSnapshot.jobRecords));
		setSavedSearches(nextSnapshot.savedSearches);
		setRetainedJobDetails(indexByJobId(nextSnapshot.retainedJobDetails));
		await writeIndexedSnapshot(nextSnapshot);
		return { ok: true, data: createJobsLocalExportEnvelope(nextSnapshot) };
	}, [jobRecords, retainedJobDetails, savedSearches, settings]);

	const snapshot = useMemo(
		(): JobsLocalSnapshot => ({
			settings,
			jobRecords: Object.values(jobRecords),
			savedSearches,
			retainedJobDetails: Object.values(retainedJobDetails),
		}),
		[jobRecords, retainedJobDetails, savedSearches, settings],
	);

	const reconcileSnapshot = useCallback(
		(rows: SearchRow[], manifest: SearchManifest | null) => {
			if (!rows.length) {
				return;
			}
			const result = reconcileJobsLocalSnapshot({
				snapshot,
				rows,
				manifest,
			});
			setJobRecords(indexByJobId(result.jobRecords));
			setRetainedJobDetails(indexByJobId(result.retainedJobDetails));
			for (const record of result.jobRecords) {
				void writeStoreRecord(JOB_RECORD_STORE, record);
			}
			for (const jobId of result.prunedRetainedJobIds) {
				void deleteStoreRecord(RETAINED_DETAIL_STORE, jobId);
			}
		},
		[snapshot],
	);

	return {
		settings,
		setSettings,
		jobRecords,
		savedSearches,
		retainedJobDetails,
		storageStatus,
		summary: summarizeJobsLocalData(snapshot),
		markViewed,
		toggleJobFlag,
		updateNotes,
		retainJobDetail,
		createSavedSearch,
		updateSavedSearch,
		deleteSavedSearch,
		duplicateSavedSearch,
		markSavedSearchReviewed,
		clearCategory,
		exportLocalData,
		importLocalData,
		reconcileSnapshot,
	};
}

function browserLocalStorage() {
	return typeof window === "undefined" ? undefined : window.localStorage;
}

function hasBrowserIndexedDb() {
	return typeof indexedDB !== "undefined";
}

function stringOr(value: unknown, fallback: string) {
	return typeof value === "string" && value.trim() ? value : fallback;
}

function nullableString(value: unknown) {
	return typeof value === "string" && value.trim() ? value : null;
}

function isPresent<T>(value: T | null | undefined): value is T {
	return value !== null && value !== undefined;
}

function approximateJsonBytes(value: unknown) {
	return new TextEncoder().encode(JSON.stringify(value)).length;
}

function formatImportLimit(bytes: number) {
	if (bytes % (1024 * 1024) === 0) {
		return `${bytes / (1024 * 1024)}MB`;
	}
	return `${bytes.toLocaleString()} bytes`;
}

function createLocalId(prefix: string, now: string) {
	const random =
		typeof crypto !== "undefined" && "randomUUID" in crypto
			? crypto.randomUUID()
			: Math.random().toString(36).slice(2);
	return `${prefix}_${now.replace(/[^0-9]/g, "")}_${random}`;
}

function defaultSavedSearchLabel(filters: JobBoardFilters) {
	const parts = [
		filters.query ? `"${filters.query}"` : "",
		filters.source,
		filters.provider,
		filters.location,
		filters.skill,
	].filter(Boolean);
	return parts.length > 0 ? parts.slice(0, 3).join(" / ") : "Saved search";
}

function clearPatchForCategory(
	category: "applied" | "hidden" | "notes" | "saved" | "viewed",
) {
	switch (category) {
		case "applied":
			return { appliedAt: null };
		case "hidden":
			return { hiddenAt: null };
		case "notes":
			return { notes: "" };
		case "saved":
			return { savedAt: null };
		case "viewed":
			return { viewedAt: null };
	}
}

function shouldPruneRetainedDetail(
	firstAbsentSnapshotAt: string,
	retention: JobsRetentionMonths,
	now: string,
) {
	if (retention === "forever") {
		return false;
	}
	const absentAt = new Date(firstAbsentSnapshotAt);
	const nowDate = new Date(now);
	if (Number.isNaN(absentAt.getTime()) || Number.isNaN(nowDate.getTime())) {
		return false;
	}
	const pruneAt = new Date(absentAt);
	pruneAt.setMonth(pruneAt.getMonth() + retention);
	return pruneAt <= nowDate;
}

function indexByJobId<T extends { jobId: string }>(records: T[]) {
	return Object.fromEntries(records.map((record) => [record.jobId, record]));
}

function indexById<T extends { id: string }>(records: T[]) {
	return Object.fromEntries(records.map((record) => [record.id, record]));
}

function mergeByUpdatedAt<T extends { jobId: string; updatedAt: string }>(
	current: Record<string, T>,
	incoming: T[],
) {
	const next = { ...current };
	for (const record of incoming) {
		const existing = next[record.jobId];
		if (!existing || existing.updatedAt <= record.updatedAt) {
			next[record.jobId] = record;
		}
	}
	return next;
}

function mergeById<T extends { id: string; updatedAt: string }>(
	current: Record<string, T>,
	incoming: T[],
) {
	const next = { ...current };
	for (const record of incoming) {
		const existing = next[record.id];
		if (!existing || existing.updatedAt <= record.updatedAt) {
			next[record.id] = record;
		}
	}
	return next;
}

async function openJobsLocalDatabase() {
	if (!hasBrowserIndexedDb()) {
		return null;
	}
	if (!dbPromise) {
		dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open(JOBS_LOCAL_DB_NAME, JOBS_LOCAL_DB_VERSION);
			request.onupgradeneeded = () => {
				const db = request.result;
				if (!db.objectStoreNames.contains(JOB_RECORD_STORE)) {
					db.createObjectStore(JOB_RECORD_STORE, { keyPath: "jobId" });
				}
				if (!db.objectStoreNames.contains(SAVED_SEARCH_STORE)) {
					db.createObjectStore(SAVED_SEARCH_STORE, { keyPath: "id" });
				}
				if (!db.objectStoreNames.contains(RETAINED_DETAIL_STORE)) {
					db.createObjectStore(RETAINED_DETAIL_STORE, { keyPath: "jobId" });
				}
			};
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		}).catch((error) => {
			dbPromise = null;
			throw error;
		});
	}
	return dbPromise;
}

async function readIndexedJobsLocalSnapshot(): Promise<JobsLocalIndexedSnapshot> {
	const [jobRecords, savedSearches, retainedJobDetails] = await Promise.all([
		readAllFromStore<JobWorkflowRecord>(JOB_RECORD_STORE),
		readAllFromStore<SavedSearchRecord>(SAVED_SEARCH_STORE),
		readAllFromStore<RetainedJobDetailRecord>(RETAINED_DETAIL_STORE),
	]);
	return {
		jobRecords: jobRecords.map((record) => normalizeJobWorkflowRecord(record)).filter(isPresent),
		savedSearches: savedSearches
			.map((record) => normalizeSavedSearchRecord(record))
			.filter(isPresent),
		retainedJobDetails: retainedJobDetails
			.map((record) => normalizeRetainedJobDetailRecord(record))
			.filter(isPresent),
	};
}

async function writeIndexedSnapshot(snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope) {
	await Promise.all([
		...snapshot.jobRecords.map((record) => writeStoreRecord(JOB_RECORD_STORE, record)),
		...snapshot.savedSearches.map((record) =>
			writeStoreRecord(SAVED_SEARCH_STORE, record),
		),
		...snapshot.retainedJobDetails.map((record) =>
			writeStoreRecord(RETAINED_DETAIL_STORE, record),
		),
	]);
}

async function clearIndexedJobsLocalData() {
	await Promise.all([
		clearStore(JOB_RECORD_STORE),
		clearStore(SAVED_SEARCH_STORE),
		clearStore(RETAINED_DETAIL_STORE),
	]);
}

async function readAllFromStore<T>(storeName: string): Promise<T[]> {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return [];
	}
	return new Promise((resolve, reject) => {
		const transaction = db.transaction(storeName, "readonly");
		const request = transaction.objectStore(storeName).getAll();
		request.onsuccess = () => resolve(request.result as T[]);
		request.onerror = () => reject(request.error);
	});
}

async function writeStoreRecord(storeName: string, value: unknown) {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return;
	}
	await new Promise<void>((resolve, reject) => {
		const transaction = db.transaction(storeName, "readwrite");
		transaction.oncomplete = () => resolve();
		transaction.onerror = () => reject(transaction.error);
		transaction.objectStore(storeName).put(value);
	});
}

async function deleteStoreRecord(storeName: string, key: string) {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return;
	}
	await new Promise<void>((resolve, reject) => {
		const transaction = db.transaction(storeName, "readwrite");
		transaction.oncomplete = () => resolve();
		transaction.onerror = () => reject(transaction.error);
		transaction.objectStore(storeName).delete(key);
	});
}

async function clearStore(storeName: string) {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return;
	}
	await new Promise<void>((resolve, reject) => {
		const transaction = db.transaction(storeName, "readwrite");
		transaction.oncomplete = () => resolve();
		transaction.onerror = () => reject(transaction.error);
		transaction.objectStore(storeName).clear();
	});
}
