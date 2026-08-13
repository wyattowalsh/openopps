import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import {
	DEFAULT_JOBS_LOCAL_SETTINGS,
	JOBS_LOCAL_IMPORT_MAX_BYTES,
	JOBS_LOCAL_IMPORT_MAX_RECORDS,
	JOBS_LOCAL_SCHEMA_VERSION,
	RETENTION_VALUES,
	type JobLifecycleBaseline,
	type JobLifecycleIndicator,
	type JobsLocalExportEnvelope,
	type JobsLocalReconciliationResult,
	type JobsLocalSettings,
	type JobsLocalSnapshot,
	type JobsLocalSummary,
	type JobWorkflowRecord,
	type JobsRetentionMonths,
	type RetainedJobDetailRecord,
	type SavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-types";
import type {
	JobDetail,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";
import { safeJobExternalUrl } from "@/lib/job-url";

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
	const baselineScope =
		candidate.baselineScope === "full" || candidate.baselineScope === "cursor"
			? candidate.baselineScope
			: "page";
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
	const reviewCursor = normalizeReviewCursor(candidate.reviewCursor);
	const baselineTotalMatches =
		typeof candidate.baselineTotalMatches === "number" &&
		Number.isFinite(candidate.baselineTotalMatches)
			? Math.max(0, Math.trunc(candidate.baselineTotalMatches))
			: baselineScope === "full" || baselineScope === "cursor"
				? reviewedJobIds.length
				: null;
	const completeBaseline = isCompleteSavedSearchBaselineValue({
		baselineScope,
		baselineTotalMatches,
		baseline: { reviewedJobIds, reviewedFingerprints },
	});
	const reviewStatus =
		candidate.schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
		candidate.reviewStatus === "current" &&
		reviewCursor &&
		completeBaseline
			? "current"
			: "needs-review";
	return {
		schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
		id,
		label: stringOr(candidate.label, "Saved search"),
		filters: normalizeSavedSearchFilters(candidate.filters),
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
		baselineTotalMatches,
		reviewStatus,
		reviewCursor: reviewStatus === "current" ? reviewCursor : null,
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
	if (
		!jobId ||
		!candidate.detail ||
		typeof candidate.detail !== "object" ||
		(candidate.detail as { id?: unknown }).id !== jobId
	) {
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

function normalizeSavedSearchFilters(value: unknown): JobBoardFilters {
	const candidate =
		value && typeof value === "object" && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: {};
	return Object.fromEntries(
		Object.entries(DEFAULT_JOB_BOARD_FILTERS).map(([key, defaultValue]) => {
			const incoming = candidate[key];
			return [key, typeof incoming === typeof defaultValue ? incoming : defaultValue];
		}),
	) as JobBoardFilters;
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
		detail: sanitizeRetainedJobDetail(detail),
	};
}

export function createSavedSearchRecord({
	filters,
	rows,
	baseline,
	baselineScope = "cursor",
	baselineTotalMatches,
	reviewStatus = "current",
	reviewCursor,
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
	reviewStatus?: SavedSearchRecord["reviewStatus"];
	reviewCursor?: SavedSearchRecord["reviewCursor"];
	label?: string;
	sortKey: JobSortKey;
	manifest: SearchManifest | null;
	now: string;
}): SavedSearchRecord {
	const resolvedBaseline = baseline ?? baselineFromRows(rows);
	const resolvedTotalMatches =
		baselineScope === "full" || baselineScope === "cursor"
			? baselineTotalMatches ?? resolvedBaseline.reviewedJobIds.length
			: baselineTotalMatches ?? null;
	const completeBaseline = isCompleteSavedSearchBaselineValue({
		baselineScope,
		baselineTotalMatches: resolvedTotalMatches,
		baseline: resolvedBaseline,
	});
	const resolvedReviewStatus =
		reviewStatus === "current" && completeBaseline ? "current" : "needs-review";
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
		baselineTotalMatches: resolvedTotalMatches,
		reviewStatus: resolvedReviewStatus,
		reviewCursor:
			resolvedReviewStatus === "current"
				? reviewCursor ?? {
						semantics: "first-seen-v1",
						reviewedAt: now,
						snapshotAt: manifest?.snapshotAt ?? null,
					}
				: null,
		baseline: resolvedBaseline,
	};
}

export function isCompleteSavedSearchBaseline(
	record: Pick<
		SavedSearchRecord,
		"baseline" | "baselineScope" | "baselineTotalMatches"
	>,
) {
	return isCompleteSavedSearchBaselineValue(record);
}

export function duplicateSavedSearchRecord(
	record: SavedSearchRecord,
	now = new Date().toISOString(),
) {
	const duplicate = normalizeSavedSearchRecord({
		...record,
		id: createLocalId("search", now),
		label: `${record.label} copy`,
		createdAt: now,
		updatedAt: now,
		lastOpenedAt: null,
	}, now);
	if (!duplicate) {
		throw new Error("The saved search is invalid and could not be duplicated.");
	}
	return duplicate;
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

export function baselineLookupFromSavedSearch(
	record: SavedSearchRecord | null | undefined,
): JobLifecycleBaseline | null {
	if (
		!record ||
		record.reviewStatus !== "current" ||
		!isCompleteSavedSearchBaseline(record)
	) {
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
	complete,
	now = new Date().toISOString(),
}: {
	snapshot: JobsLocalSnapshot;
	rows: SearchRow[];
	manifest: SearchManifest | null;
	complete: boolean;
	now?: string;
}): JobsLocalReconciliationResult | null {
	if (
		!complete ||
		!manifest ||
		!isIsoTimestamp(manifest.snapshotAt) ||
		!Number.isInteger(manifest.entities.jobs.count) ||
		manifest.entities.jobs.count < 0 ||
		rows.length !== manifest.entities.jobs.count
	) {
		return null;
	}
	const rowIds = rows.map((row) => text(row[J.id]));
	if (rowIds.some((jobId) => !jobId) || new Set(rowIds).size !== rowIds.length) {
		return null;
	}
	const snapshotAt = manifest.snapshotAt;
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

function isCompleteSavedSearchBaselineValue({
	baselineScope,
	baselineTotalMatches,
	baseline,
}: Pick<
	SavedSearchRecord,
	"baseline" | "baselineScope" | "baselineTotalMatches"
>) {
	if (
		baselineScope !== "full" ||
		!Number.isInteger(baselineTotalMatches) ||
		baselineTotalMatches === null ||
		baselineTotalMatches < 0
	) {
		return false;
	}
	const uniqueIds = new Set(baseline.reviewedJobIds);
	const fingerprintIds = Object.keys(baseline.reviewedFingerprints);
	return (
		uniqueIds.size === baseline.reviewedJobIds.length &&
		uniqueIds.size === baselineTotalMatches &&
		fingerprintIds.length === uniqueIds.size &&
		fingerprintIds.every((jobId) => uniqueIds.has(jobId)) &&
		baseline.reviewedJobIds.every(
			(jobId) => Boolean(jobId) && Boolean(baseline.reviewedFingerprints[jobId]),
		)
	);
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
	let serialized: string;
	try {
		const encoded = typeof value === "string" ? value : JSON.stringify(value);
		if (typeof encoded !== "string") {
			return { ok: false, errors: ["Import payload must be serializable JSON."] };
		}
		serialized = encoded;
	} catch {
		return { ok: false, errors: ["Import payload must be serializable JSON."] };
	}
	const byteLength = new TextEncoder().encode(serialized).length;
	if (byteLength > JOBS_LOCAL_IMPORT_MAX_BYTES) {
		return {
			ok: false,
			errors: [
				`Import file exceeds the ${formatImportLimit(JOBS_LOCAL_IMPORT_MAX_BYTES)} size limit.`,
			],
		};
	}
	let parsed: unknown = value;
	if (typeof value === "string") {
		try {
			parsed = JSON.parse(value);
		} catch {
			return { ok: false, errors: ["Import file is not valid JSON."] };
		}
	}
	if (!isPlainRecord(parsed)) {
		return { ok: false, errors: ["Import payload must be an object."] };
	}
	const candidate = parsed as {
		source?: string;
		schemaVersion?: number;
		exportedAt?: unknown;
		settings?: unknown;
		jobRecords?: unknown;
		savedSearches?: unknown;
		retainedJobDetails?: unknown;
	};
	// Accept schema v1 imports (migrated on normalize) and current schema version.
	const schemaVersion = candidate.schemaVersion;
	if (
		candidate.source !== "openopps.jobs.local" ||
		(schemaVersion !== 1 && schemaVersion !== JOBS_LOCAL_SCHEMA_VERSION)
	) {
		return {
			ok: false,
			errors: ["Import payload is not an OpenOpps jobs local data backup."],
		};
	}
	const jobRecords = Array.isArray(candidate.jobRecords)
		? candidate.jobRecords
		: [];
	const savedSearches = Array.isArray(candidate.savedSearches)
		? candidate.savedSearches
		: [];
	const retainedJobDetails = Array.isArray(candidate.retainedJobDetails)
		? candidate.retainedJobDetails
		: [];
	const recordCount =
		jobRecords.length + savedSearches.length + retainedJobDetails.length;
	if (recordCount > JOBS_LOCAL_IMPORT_MAX_RECORDS) {
		return {
			ok: false,
			errors: [
				`Import payload exceeds the ${JOBS_LOCAL_IMPORT_MAX_RECORDS.toLocaleString()} record limit.`,
			],
		};
	}
	const structureErrors = validateImportStructure(candidate, schemaVersion);
	if (structureErrors.length > 0) {
		return { ok: false, errors: structureErrors };
	}
	const now = new Date().toISOString();
	const normalizedJobs = jobRecords.map((record) =>
		normalizeJobWorkflowRecord(record, now),
	);
	const normalizedSearches = savedSearches.map((record) =>
		normalizeSavedSearchRecord(record, now),
	);
	const normalizedDetails = retainedJobDetails.map((record) =>
		normalizeRetainedJobDetailRecord(record, now),
	);
	if (
		normalizedJobs.some((record) => !record) ||
		normalizedSearches.some((record) => !record) ||
		normalizedDetails.some((record) => !record)
	) {
		return {
			ok: false,
			errors: ["Import payload contains a record that cannot be normalized safely."],
		};
	}
	return {
		ok: true,
		data: {
			source: "openopps.jobs.local",
			schemaVersion: JOBS_LOCAL_SCHEMA_VERSION,
			exportedAt: stringOr(candidate.exportedAt, now),
			settings: normalizeJobsLocalSettings(candidate.settings),
			jobRecords: normalizedJobs.filter(isPresent),
			savedSearches: normalizedSearches.filter(isPresent),
			retainedJobDetails: normalizedDetails.filter(isPresent),
		},
	};
}

export function indexByJobId<T extends { jobId: string }>(records: T[]) {
	return Object.fromEntries(records.map((record) => [record.jobId, record]));
}

export function clearPatchForCategory(
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

const IMPORT_ROOT_KEYS = new Set([
	"source",
	"schemaVersion",
	"exportedAt",
	"settings",
	"jobRecords",
	"savedSearches",
	"retainedJobDetails",
]);
const SETTINGS_KEYS = new Set([
	"schemaVersion",
	"fullDetailRetentionMonths",
	"showHidden",
	"hideViewed",
	"dismissedStorageNotice",
	"lastRepairMessage",
]);
const JOB_RECORD_KEYS = new Set([
	"schemaVersion",
	"jobId",
	"createdAt",
	"updatedAt",
	"viewedAt",
	"savedAt",
	"hiddenAt",
	"appliedAt",
	"notes",
	"firstSeenSnapshotAt",
	"lastSeenSnapshotAt",
	"firstAbsentSnapshotAt",
	"lastKnownFingerprint",
	"lastKnownTitle",
	"lastKnownCompany",
]);
const SAVED_SEARCH_KEYS = new Set([
	"schemaVersion",
	"id",
	"label",
	"filters",
	"sortKey",
	"visibleColumns",
	"createdAt",
	"updatedAt",
	"lastOpenedAt",
	"lastReviewedAt",
	"manifestVersion",
	"snapshotAt",
	"baselineScope",
	"baselineTotalMatches",
	"reviewStatus",
	"reviewCursor",
	"baseline",
]);
const RETAINED_DETAIL_KEYS = new Set([
	"schemaVersion",
	"jobId",
	"capturedAt",
	"updatedAt",
	"snapshotAt",
	"rowSnapshot",
	"detail",
]);
const JOB_DETAIL_KEYS = new Set([
	"id",
	"status",
	"sourceKey",
	"boardKey",
	"providerId",
	"remoteId",
	"title",
	"company",
	"department",
	"team",
	"workplaceType",
	"remote",
	"employmentType",
	"locations",
	"salaryMin",
	"salaryMax",
	"salaryCurrency",
	"description",
	"responsibilities",
	"qualifications",
	"skills",
	"jobDescription",
	"compensation",
	"experience",
	"salary",
	"applyUrl",
	"postingUrl",
	"postedAt",
	"updatedAt",
	"versionCreatedAt",
	"firstSeenAt",
	"lastSeenAt",
	"closedAt",
	"syncedAt",
	"version",
	"contentHash",
	"payloadHash",
	"detailTier",
	"jobExtra",
	"versionExtra",
]);
const SKILL_KEYS = new Set(["name", "level", "keywords"]);
const FILTER_KEYS = new Set(Object.keys(DEFAULT_JOB_BOARD_FILTERS));
const FORBIDDEN_IMPORT_KEYS = new Set([
	"__proto__",
	"constructor",
	"prototype",
	"payloadSnapshots",
	"descriptionHtml",
]);

function validateImportStructure(
	candidate: object,
	schemaVersion: number,
) {
	const errors: string[] = [];
	const root = candidate as Record<string, unknown>;
	if (!hasExactKeys(root, IMPORT_ROOT_KEYS)) {
		errors.push("Import payload has unexpected or missing top-level fields.");
	}
	if (!isIsoTimestamp(root.exportedAt)) {
		errors.push("Import exportedAt must be a valid timestamp.");
	}
	if (!isPlainRecord(root.settings)) {
		errors.push("Import settings must be an object.");
	} else {
		if (
			!hasOnlyKeys(root.settings, SETTINGS_KEYS) ||
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
				!hasExactKeys(root.settings, SETTINGS_KEYS))
		) {
			errors.push("Import settings contain unsupported fields.");
		}
		for (const key of ["showHidden", "hideViewed", "dismissedStorageNotice"]) {
			if (key in root.settings && typeof root.settings[key] !== "boolean") {
				errors.push(`Import setting ${key} must be boolean.`);
			}
		}
		if (
			"fullDetailRetentionMonths" in root.settings &&
			!RETENTION_VALUES.has(
				root.settings.fullDetailRetentionMonths as JobsRetentionMonths,
			)
		) {
			errors.push("Import detail retention setting is invalid.");
		}
		if (
			"lastRepairMessage" in root.settings &&
			root.settings.lastRepairMessage !== null &&
			typeof root.settings.lastRepairMessage !== "string"
		) {
			errors.push("Import last repair message is invalid.");
		}
	}
	if (
		!Array.isArray(root.jobRecords) ||
		!Array.isArray(root.savedSearches) ||
		!Array.isArray(root.retainedJobDetails)
	) {
		errors.push("Import record collections must all be arrays.");
		return errors;
	}

	const jobIds = new Set<string>();
	for (const [index, value] of root.jobRecords.entries()) {
		if (
			!isPlainRecord(value) ||
			!hasOnlyKeys(value, JOB_RECORD_KEYS) ||
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
				!hasExactKeys(value, JOB_RECORD_KEYS))
		) {
			errors.push(`Import jobRecords[${index}] has an invalid shape.`);
			continue;
		}
		const jobId = validLocalId(value.jobId);
		if (!jobId || jobIds.has(jobId)) {
			errors.push(`Import jobRecords[${index}] has a missing or duplicate jobId.`);
		} else {
			jobIds.add(jobId);
		}
		if (!validRecordVersion(value.schemaVersion, schemaVersion)) {
			errors.push(`Import jobRecords[${index}] has an invalid schemaVersion.`);
		}
		if (
			!validRequiredTimestamp(value.createdAt, schemaVersion === 1) ||
			!validRequiredTimestamp(value.updatedAt, schemaVersion === 1)
		) {
			errors.push(`Import jobRecords[${index}] has invalid timestamps.`);
		}
		for (const key of [
			"viewedAt",
			"savedAt",
			"hiddenAt",
			"appliedAt",
			"firstSeenSnapshotAt",
			"lastSeenSnapshotAt",
			"firstAbsentSnapshotAt",
		]) {
			if (key in value && !validNullableTimestamp(value[key])) {
				errors.push(`Import jobRecords[${index}].${key} is invalid.`);
			}
		}
		if ("notes" in value && typeof value.notes !== "string") {
			errors.push(`Import jobRecords[${index}].notes must be a string.`);
		}
		for (const key of [
			"lastKnownFingerprint",
			"lastKnownTitle",
			"lastKnownCompany",
		]) {
			if (key in value && !validNullableString(value[key])) {
				errors.push(`Import jobRecords[${index}].${key} is invalid.`);
			}
		}
	}

	const searchIds = new Set<string>();
	for (const [index, value] of root.savedSearches.entries()) {
		if (
			!isPlainRecord(value) ||
			!hasOnlyKeys(value, SAVED_SEARCH_KEYS) ||
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
				!hasExactKeys(value, SAVED_SEARCH_KEYS))
		) {
			errors.push(`Import savedSearches[${index}] has an invalid shape.`);
			continue;
		}
		const id = validLocalId(value.id);
		if (!id || searchIds.has(id)) {
			errors.push(`Import savedSearches[${index}] has a missing or duplicate id.`);
		} else {
			searchIds.add(id);
		}
		if (!validRecordVersion(value.schemaVersion, schemaVersion)) {
			errors.push(`Import savedSearches[${index}] has an invalid schemaVersion.`);
		}
		if (
			!validRequiredTimestamp(value.createdAt, schemaVersion === 1) ||
			!validRequiredTimestamp(value.updatedAt, schemaVersion === 1)
		) {
			errors.push(`Import savedSearches[${index}] has invalid timestamps.`);
		}
		if (!validImportedFilters(value.filters)) {
			errors.push(`Import savedSearches[${index}].filters are invalid.`);
		}
		if (
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION || "sortKey" in value) &&
			value.sortKey !== "latest" &&
			value.sortKey !== "relevance"
		) {
			errors.push(`Import savedSearches[${index}].sortKey is invalid.`);
		}
		if (
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION || "visibleColumns" in value) &&
			(!Array.isArray(value.visibleColumns) ||
				!value.visibleColumns.every(isString))
		) {
			errors.push(`Import savedSearches[${index}].visibleColumns are invalid.`);
		}
		if (
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION || "baseline" in value) &&
			!validSavedSearchBaseline(value)
		) {
			errors.push(`Import savedSearches[${index}] has an invalid baseline.`);
		}
		if (
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION || "label" in value) &&
			(typeof value.label !== "string" || !value.label.trim())
		) {
			errors.push(`Import savedSearches[${index}].label is invalid.`);
		}
		for (const key of ["lastOpenedAt", "lastReviewedAt", "snapshotAt"]) {
			if (key in value && !validNullableTimestamp(value[key])) {
				errors.push(`Import savedSearches[${index}].${key} is invalid.`);
			}
		}
		if (
			"manifestVersion" in value &&
			value.manifestVersion !== null &&
			(!Number.isInteger(value.manifestVersion) ||
				typeof value.manifestVersion !== "number" ||
				value.manifestVersion < 0)
		) {
			errors.push(`Import savedSearches[${index}].manifestVersion is invalid.`);
		}
		if (
			schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
			!validReviewState(value)
		) {
			errors.push(`Import savedSearches[${index}] has an invalid review state.`);
		}
	}

	const retainedIds = new Set<string>();
	for (const [index, value] of root.retainedJobDetails.entries()) {
		if (
			!isPlainRecord(value) ||
			!hasOnlyKeys(value, RETAINED_DETAIL_KEYS) ||
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION &&
				!hasExactKeys(value, RETAINED_DETAIL_KEYS))
		) {
			errors.push(`Import retainedJobDetails[${index}] has an invalid shape.`);
			continue;
		}
		const jobId = validLocalId(value.jobId);
		if (!jobId || retainedIds.has(jobId)) {
			errors.push(`Import retainedJobDetails[${index}] has a missing or duplicate jobId.`);
		} else {
			retainedIds.add(jobId);
		}
		if (!validRecordVersion(value.schemaVersion, schemaVersion)) {
			errors.push(`Import retainedJobDetails[${index}] has an invalid schemaVersion.`);
		}
		if (
			!validRequiredTimestamp(value.capturedAt, schemaVersion === 1) ||
			!validRequiredTimestamp(value.updatedAt, schemaVersion === 1)
		) {
			errors.push(`Import retainedJobDetails[${index}] has invalid timestamps.`);
		}
		if (
			!validImportedJobDetail(value.detail, jobId)
		) {
			errors.push(`Import retainedJobDetails[${index}].detail is invalid or private.`);
		}
		if (
			(schemaVersion === JOBS_LOCAL_SCHEMA_VERSION || "rowSnapshot" in value) &&
			!validImportedSearchRow(value.rowSnapshot)
		) {
			errors.push(`Import retainedJobDetails[${index}].rowSnapshot is invalid.`);
		}
		if ("snapshotAt" in value && !validNullableTimestamp(value.snapshotAt)) {
			errors.push(`Import retainedJobDetails[${index}].snapshotAt is invalid.`);
		}
	}
	return errors.slice(0, 20);
}

function validSavedSearchBaseline(value: Record<string, unknown>) {
	if (
		!isPlainRecord(value.baseline) ||
		!hasExactKeys(
			value.baseline,
			new Set(["reviewedJobIds", "reviewedFingerprints"]),
		) ||
		!Array.isArray(value.baseline.reviewedJobIds) ||
		!value.baseline.reviewedJobIds.every((item) => Boolean(validLocalId(item))) ||
		new Set(value.baseline.reviewedJobIds).size !==
			value.baseline.reviewedJobIds.length ||
		!isPlainRecord(value.baseline.reviewedFingerprints)
	) {
		return false;
	}
	const reviewedIds = new Set(value.baseline.reviewedJobIds as string[]);
	const fingerprints = Object.entries(value.baseline.reviewedFingerprints);
	return (
		fingerprints.length === reviewedIds.size &&
		fingerprints.every(
		([jobId, fingerprint]) =>
			reviewedIds.has(jobId) &&
			Boolean(validLocalId(jobId)) &&
			typeof fingerprint === "string" &&
			Boolean(fingerprint.trim()),
		)
	);
}

function validReviewState(value: Record<string, unknown>) {
	if (
		(value.baselineScope !== "page" &&
			value.baselineScope !== "cursor" &&
			value.baselineScope !== "full") ||
		(value.reviewStatus !== "current" && value.reviewStatus !== "needs-review") ||
		(value.baselineTotalMatches !== null &&
			(!Number.isInteger(value.baselineTotalMatches) ||
				typeof value.baselineTotalMatches !== "number" ||
				value.baselineTotalMatches < 0))
	) {
		return false;
	}
	if (value.reviewStatus === "needs-review") {
		return value.reviewCursor === null;
	}
	if (!isPlainRecord(value.reviewCursor)) {
		return false;
	}
	if (!validSavedSearchBaseline(value)) {
		return false;
	}
	const baseline = value.baseline as {
		reviewedJobIds: string[];
		reviewedFingerprints: Record<string, string>;
	};
	return (
		value.baselineScope === "full" &&
		value.reviewCursor.semantics === "first-seen-v1" &&
		isIsoTimestamp(value.reviewCursor.reviewedAt) &&
		validNullableTimestamp(value.reviewCursor.snapshotAt) &&
			hasExactKeys(
				value.reviewCursor,
				new Set(["semantics", "reviewedAt", "snapshotAt"]),
		) &&
		isCompleteSavedSearchBaselineValue({
			baselineScope: "full",
			baselineTotalMatches: value.baselineTotalMatches as number | null,
			baseline,
		})
	);
}

function validImportedJobDetail(value: unknown, jobId: string | null) {
	if (
		!jobId ||
		!isPlainRecord(value) ||
		value.id !== jobId ||
		!hasOnlyKeys(value, JOB_DETAIL_KEYS) ||
		containsForbiddenImportKey(value)
	) {
		return false;
	}
	const nullableStrings = [
		"status",
		"sourceKey",
		"boardKey",
		"providerId",
		"remoteId",
		"title",
		"company",
		"department",
		"team",
		"workplaceType",
		"remote",
		"employmentType",
		"salaryCurrency",
		"description",
		"experience",
		"salary",
		"postedAt",
		"updatedAt",
		"versionCreatedAt",
		"firstSeenAt",
		"lastSeenAt",
		"closedAt",
		"syncedAt",
		"contentHash",
		"payloadHash",
		"detailTier",
	];
	if (
		nullableStrings.some(
			(key) => key in value && !validNullableString(value[key]),
		)
	) {
		return false;
	}
	for (const key of ["salaryMin", "salaryMax", "version"]) {
		if (
			key in value &&
			value[key] !== null &&
			(typeof value[key] !== "number" || !Number.isFinite(value[key]))
		) {
			return false;
		}
	}
	for (const key of ["locations", "responsibilities", "qualifications"]) {
		if (
			key in value &&
			(!Array.isArray(value[key]) || !value[key].every(isString))
		) {
			return false;
		}
	}
	if (
		"skills" in value &&
		(!Array.isArray(value.skills) ||
			!value.skills.every(
				(skill) =>
					isPlainRecord(skill) &&
					hasOnlyKeys(skill, SKILL_KEYS) &&
					(!("name" in skill) || validOptionalString(skill.name)) &&
					(!("level" in skill) || validOptionalString(skill.level)) &&
					(!("keywords" in skill) ||
						(Array.isArray(skill.keywords) && skill.keywords.every(isString))),
			))
	) {
		return false;
	}
	for (const key of [
		"jobDescription",
		"compensation",
		"jobExtra",
		"versionExtra",
	]) {
		if (key in value && value[key] !== null && !isPlainRecord(value[key])) {
			return false;
		}
	}
	for (const key of ["applyUrl", "postingUrl"]) {
		const url = value[key];
		if (
			key in value &&
			url !== null &&
			(typeof url !== "string" || safeJobExternalUrl(url) === null)
		) {
			return false;
		}
	}
	return true;
}

function validImportedSearchRow(value: unknown) {
	return (
		value === null ||
		(Array.isArray(value) &&
			value.length <= 128 &&
			value.every(
				(item) =>
					item === null ||
					typeof item === "string" ||
					(typeof item === "number" && Number.isFinite(item)),
			))
	);
}

function validImportedFilters(value: unknown) {
	if (!isPlainRecord(value) || !hasOnlyKeys(value, FILTER_KEYS)) {
		return false;
	}
	return Object.entries(DEFAULT_JOB_BOARD_FILTERS).every(([key, defaultValue]) => {
		const incoming = value[key];
		return typeof incoming === typeof defaultValue;
	});
}

function containsForbiddenImportKey(value: unknown): boolean {
	const pending: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
	let visited = 0;
	while (pending.length > 0) {
		const current = pending.pop();
		if (!current) {
			continue;
		}
		visited += 1;
		if (visited > 20_000 || current.depth > 32) {
			return true;
		}
		if (Array.isArray(current.value)) {
			for (const nested of current.value) {
				pending.push({ value: nested, depth: current.depth + 1 });
			}
			continue;
		}
		if (!isPlainRecord(current.value)) {
			continue;
		}
		for (const [key, nested] of Object.entries(current.value)) {
			if (FORBIDDEN_IMPORT_KEYS.has(key)) {
				return true;
			}
			pending.push({ value: nested, depth: current.depth + 1 });
		}
	}
	return false;
}

function validRecordVersion(value: unknown, envelopeVersion: number) {
	return value === undefined || value === envelopeVersion;
}

function validLocalId(value: unknown) {
	if (typeof value !== "string") {
		return null;
	}
	const id = value.trim();
	return id && value === id && id.length <= 1_024 && !id.includes("\0")
		? id
		: null;
}

function isIsoTimestamp(value: unknown) {
	return (
		typeof value === "string" &&
		/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
		Number.isFinite(Date.parse(value))
	);
}

function validRequiredTimestamp(value: unknown, allowMissing: boolean) {
	return (allowMissing && value === undefined) || isIsoTimestamp(value);
}

function validNullableTimestamp(value: unknown) {
	return value === null || isIsoTimestamp(value);
}

function validNullableString(value: unknown) {
	return value === null || typeof value === "string";
}

function validOptionalString(value: unknown) {
	return value === undefined || typeof value === "string";
}

function isString(value: unknown): value is string {
	return typeof value === "string";
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return false;
	}
	const prototype = Object.getPrototypeOf(value);
	return prototype === Object.prototype || prototype === null;
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>) {
	return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeys(value: Record<string, unknown>, expected: ReadonlySet<string>) {
	return Object.keys(value).length === expected.size && hasOnlyKeys(value, expected);
}

function stringOr(value: unknown, fallback: string) {
	return typeof value === "string" && value.trim() ? value : fallback;
}

function normalizeReviewCursor(value: unknown): SavedSearchRecord["reviewCursor"] {
	if (!value || typeof value !== "object") {
		return null;
	}
	const candidate = value as Record<string, unknown>;
	if (
		candidate.semantics !== "first-seen-v1" ||
		typeof candidate.reviewedAt !== "string" ||
		!Number.isFinite(Date.parse(candidate.reviewedAt)) ||
		!(candidate.snapshotAt === null || typeof candidate.snapshotAt === "string")
	) {
		return null;
	}
	return {
		semantics: "first-seen-v1",
		reviewedAt: candidate.reviewedAt,
		snapshotAt: candidate.snapshotAt,
	};
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
