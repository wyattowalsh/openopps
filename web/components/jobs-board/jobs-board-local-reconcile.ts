import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
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
	JobsSearchSummaryResponse,
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