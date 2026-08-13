import { describe, expect, it } from "vitest";

import {
	DEFAULT_JOBS_LOCAL_SETTINGS,
	JOBS_LOCAL_SETTINGS_KEY,
	baselineFromRows,
	baselineLookupFromSavedSearch,
	createJobsLocalExportEnvelope,
	createJobWorkflowRecord,
	createRetainedJobDetailRecord,
	createSavedSearchRecord,
	jobFingerprint,
	jobLifecycleIndicators,
	isCompleteSavedSearchBaseline,
	mergeJobsLocalSnapshots,
	normalizeJobsLocalSettings,
	normalizeRetainedJobDetailRecord,
	normalizeSavedSearchRecord,
	parseJobsLocalImport,
	pruneRetainedJobDetailsForWorkflowRecords,
	readJobsLocalSettings,
	reconcileJobsLocalSnapshot,
	savedSearchNewMatchCount,
	summarizeJobsLocalData,
	updateJobWorkflowRecord,
	type JobsLocalSnapshot,
} from "@/components/jobs-board/jobs-board-local-state";
import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type { SearchManifest, SearchRow } from "@/components/openopps-search/search-types";
import { J } from "@/components/openopps-search/search-utils";

describe("jobs board local state", () => {
	it("normalizes settings and repairs invalid retained-detail settings", () => {
		expect(
			normalizeJobsLocalSettings({
				fullDetailRetentionMonths: 99,
				showHidden: true,
				hideViewed: true,
			}),
		).toEqual({
			...DEFAULT_JOBS_LOCAL_SETTINGS,
			showHidden: true,
			hideViewed: true,
		});
		expect(
			normalizeJobsLocalSettings({
				fullDetailRetentionMonths: "forever",
			}).fullDetailRetentionMonths,
		).toBe("forever");
	});

	it("falls back to default settings when localStorage contains invalid JSON", () => {
		const storage = memoryStorage({
			[JOBS_LOCAL_SETTINGS_KEY]: "{not json",
		});
		expect(readJobsLocalSettings(storage)).toMatchObject({
			fullDetailRetentionMonths: 6,
			lastRepairMessage:
				"Local settings were reset because the saved JSON was invalid.",
		});
	});

	it("updates local job workflow flags without losing stable metadata", () => {
		const now = "2026-06-30T03:00:00.000Z";
		const row = jobRow("job-a");
		const record = createJobWorkflowRecord({
			jobId: "job-a",
			now,
			snapshotAt: "2026-06-16T00:00:00.000Z",
			row,
		});
		const updated = updateJobWorkflowRecord(
			record,
			{ viewedAt: now, savedAt: now, notes: "follow up" },
			{
				jobId: "job-a",
				now: "2026-06-30T03:10:00.000Z",
				snapshotAt: "2026-06-30T00:00:00.000Z",
				row,
			},
		);

		expect(updated.createdAt).toBe(now);
		expect(updated.updatedAt).toBe("2026-06-30T03:10:00.000Z");
		expect(updated.viewedAt).toBe(now);
		expect(updated.savedAt).toBe(now);
		expect(updated.notes).toBe("follow up");
		expect(updated.lastKnownTitle).toBe("Platform Engineer");
		expect(updated.lastKnownFingerprint).toBe(jobFingerprint(row));
	});

	it("counts saved-search new matches from baseline ids and fingerprints", () => {
		const initial = [jobRow("job-a"), jobRow("job-b")];
		const baseline = baselineFromRows(initial);
		const record = {
			...createSavedSearchRecord({
				filters: DEFAULT_JOB_BOARD_FILTERS,
				rows: initial,
				sortKey: "latest",
				manifest: manifest(),
				now: "2026-06-30T03:00:00.000Z",
			}),
			baseline,
		};
		expect(savedSearchNewMatchCount(record, initial)).toBe(0);
		expect(
			savedSearchNewMatchCount(record, [
				jobRow("job-a", { latestObserved: "2026-07-01T00:00:00.000Z" }),
				jobRow("job-b"),
				jobRow("job-c"),
			]),
		).toBe(2);
	});

	it("normalizes legacy saved searches as page-scoped baselines", () => {
		const record = normalizeSavedSearchRecord({
			id: "search-1",
			label: "Platform",
			filters: DEFAULT_JOB_BOARD_FILTERS,
			sortKey: "latest",
			baseline: {
				reviewedJobIds: ["job-a"],
				reviewedFingerprints: { "job-a": "content-v1" },
			},
		});

		expect(record?.baselineScope).toBe("page");
		expect(record?.baselineTotalMatches).toBeNull();
		expect(record?.baseline.reviewedJobIds).toEqual(["job-a"]);
	});

	it("only treats complete full-membership saved-search baselines as current", () => {
		const rows = [jobRow("job-a"), jobRow("job-b")];
		const partial = createSavedSearchRecord({
			filters: DEFAULT_JOB_BOARD_FILTERS,
			rows: rows.slice(0, 1),
			baselineScope: "cursor",
			baselineTotalMatches: rows.length,
			reviewStatus: "current",
			sortKey: "latest",
			manifest: manifest(),
			now: "2026-06-30T03:00:00.000Z",
		});
		const complete = createSavedSearchRecord({
			filters: DEFAULT_JOB_BOARD_FILTERS,
			rows,
			baselineScope: "full",
			baselineTotalMatches: rows.length,
			reviewStatus: "current",
			sortKey: "latest",
			manifest: manifest(),
			now: "2026-06-30T03:00:00.000Z",
		});

		expect(partial.reviewStatus).toBe("needs-review");
		expect(partial.reviewCursor).toBeNull();
		expect(isCompleteSavedSearchBaseline(partial)).toBe(false);
		expect(baselineLookupFromSavedSearch(partial)).toBeNull();
		expect(complete.reviewStatus).toBe("current");
		expect(isCompleteSavedSearchBaseline(complete)).toBe(true);
		expect(baselineLookupFromSavedSearch(complete)?.reviewedJobIds).toEqual(
			new Set(["job-a", "job-b"]),
		);
	});

	it("prefers generated content hashes for job fingerprints when present", () => {
		const row = jobRow("job-a", {
			contentHash: "content-v1",
			payloadHash: "payload-v1",
			latestObserved: "2026-06-16T10:00:00Z",
		});

		expect(jobFingerprint(row)).toBe("content-v1|payload-v1");
	});

	it("derives local lifecycle indicators from saved-search baselines and records", () => {
		const reviewed = jobRow("job-a", { contentHash: "content-v1" });
		const baseline = {
			reviewedJobIds: new Set(["job-a"]),
			reviewedFingerprints: {
				"job-a": jobFingerprint(reviewed),
			},
		};

		expect(
			jobLifecycleIndicators({
				row: jobRow("job-b", { contentHash: "content-v1" }),
				baseline,
			}),
		).toEqual(["new"]);
		expect(
			jobLifecycleIndicators({
				row: jobRow("job-a", { contentHash: "content-v2" }),
				baseline,
			}),
		).toEqual(["changed"]);
		expect(
			jobLifecycleIndicators({
				row: jobRow("job-a", { contentHash: "content-v1", status: "closed" }),
				baseline,
			}),
		).toEqual(["stale"]);
		expect(
			jobLifecycleIndicators({
				row: jobRow("job-a", { contentHash: "content-v2" }),
				workflowRecord: createJobWorkflowRecord({
					jobId: "job-a",
					now: "2026-06-30T03:00:00.000Z",
					row: reviewed,
				}),
			}),
		).toEqual(["changed"]);
	});

	it("reconciles full snapshots and prunes retained stale details by retention", () => {
		const viewedSaved = updateJobWorkflowRecord(
			null,
			{
				savedAt: "2026-02-01T00:00:00.000Z",
				viewedAt: "2026-02-01T00:00:00.000Z",
			},
			{
				jobId: "job-a",
				now: "2026-02-01T00:00:00.000Z",
				row: jobRow("job-a", { contentHash: "content-v1" }),
				snapshotAt: "2026-02-01T00:00:00.000Z",
			},
		);
		const hiddenOnly = updateJobWorkflowRecord(
			null,
			{ hiddenAt: "2026-02-01T00:00:00.000Z" },
			{ jobId: "job-b", now: "2026-02-01T00:00:00.000Z" },
		);
		const retained = createRetainedJobDetailRecord({
			row: jobRow("job-a", { contentHash: "content-v1" }),
			detail: { id: "job-a", title: "Platform Engineer" },
			now: "2026-02-01T00:00:00.000Z",
			snapshotAt: "2026-02-01T00:00:00.000Z",
		});

		const result = reconcileJobsLocalSnapshot({
			snapshot: {
				settings: {
					...DEFAULT_JOBS_LOCAL_SETTINGS,
					fullDetailRetentionMonths: 1,
				},
				jobRecords: [viewedSaved, hiddenOnly],
				savedSearches: [],
				retainedJobDetails: [retained],
			},
			rows: [jobRow("job-c")],
			manifest: { ...manifest(1), snapshotAt: "2026-03-01T00:00:00.000Z" },
			complete: true,
			now: "2026-04-02T00:00:00.000Z",
		});

		expect(result?.jobRecords).toMatchObject([
			{
				jobId: "job-a",
				firstAbsentSnapshotAt: "2026-03-01T00:00:00.000Z",
			},
			{
				jobId: "job-b",
				firstAbsentSnapshotAt: "2026-03-01T00:00:00.000Z",
			},
		]);
		expect(result?.retainedJobDetails).toHaveLength(0);
		expect(result?.prunedRetainedJobIds).toEqual(["job-a"]);
	});

	it("refuses reconciliation for incomplete or count-mismatched snapshots", () => {
		const snapshot: JobsLocalSnapshot = {
			settings: DEFAULT_JOBS_LOCAL_SETTINGS,
			jobRecords: [
				updateJobWorkflowRecord(
					null,
					{ savedAt: "2026-06-01T00:00:00.000Z" },
					{ jobId: "job-a", now: "2026-06-01T00:00:00.000Z" },
				),
			],
			savedSearches: [],
			retainedJobDetails: [],
		};
		const rows = [jobRow("job-b")];

		expect(
			reconcileJobsLocalSnapshot({
				snapshot,
				rows,
				manifest: manifest(1),
				complete: false,
			}),
		).toBeNull();
		expect(
			reconcileJobsLocalSnapshot({
				snapshot,
				rows,
				manifest: manifest(2),
				complete: true,
			}),
		).toBeNull();
	});

	it("merges imports without letting older imported records overwrite newer local records", () => {
		const currentRecord = updateJobWorkflowRecord(
			null,
			{ savedAt: "2026-06-01T00:00:00.000Z", notes: "current" },
			{ jobId: "job-a", now: "2026-06-10T00:00:00.000Z" },
		);
		const olderImportedRecord = {
			...updateJobWorkflowRecord(
				null,
				{ savedAt: "2026-05-01T00:00:00.000Z", notes: "old import" },
				{ jobId: "job-a", now: "2026-05-10T00:00:00.000Z" },
			),
			updatedAt: "2026-05-10T00:00:00.000Z",
		};
		const newImportedRecord = updateJobWorkflowRecord(
			null,
			{ hiddenAt: "2026-06-11T00:00:00.000Z" },
			{ jobId: "job-b", now: "2026-06-11T00:00:00.000Z" },
		);

		const merged = mergeJobsLocalSnapshots(
			{
				settings: { ...DEFAULT_JOBS_LOCAL_SETTINGS, showHidden: true },
				jobRecords: [currentRecord],
				savedSearches: [],
				retainedJobDetails: [],
			},
			{
				settings: { ...DEFAULT_JOBS_LOCAL_SETTINGS, hideViewed: true },
				jobRecords: [olderImportedRecord, newImportedRecord],
				savedSearches: [],
				retainedJobDetails: [],
			},
		);

		expect(merged.settings).toMatchObject({ showHidden: true, hideViewed: true });
		expect(merged.jobRecords).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ jobId: "job-a", notes: "current" }),
				expect.objectContaining({ jobId: "job-b", hiddenAt: "2026-06-11T00:00:00.000Z" }),
			]),
		);
	});

	it("prunes retained details once no detail-retaining local state remains", () => {
		const viewedOnly = updateJobWorkflowRecord(
			null,
			{ viewedAt: "2026-06-01T00:00:00.000Z" },
			{ jobId: "job-a", now: "2026-06-01T00:00:00.000Z" },
		);
		const saved = updateJobWorkflowRecord(
			null,
			{ savedAt: "2026-06-01T00:00:00.000Z" },
			{ jobId: "job-b", now: "2026-06-01T00:00:00.000Z" },
		);
		const result = pruneRetainedJobDetailsForWorkflowRecords({
			jobRecords: {
				"job-a": viewedOnly,
				"job-b": saved,
			},
			retainedJobDetails: {
				"job-a": createRetainedJobDetailRecord({
					row: jobRow("job-a"),
					detail: { id: "job-a", title: "Viewed" },
					now: "2026-06-01T00:00:00.000Z",
				}),
				"job-b": createRetainedJobDetailRecord({
					row: jobRow("job-b"),
					detail: { id: "job-b", title: "Saved" },
					now: "2026-06-01T00:00:00.000Z",
				}),
			},
		});

		expect(Object.keys(result.retained)).toEqual(["job-b"]);
		expect(result.prunedJobIds).toEqual(["job-a"]);
	});

	it("clears stale markers when a durable job reappears in a later snapshot", () => {
		const staleSaved = {
			...updateJobWorkflowRecord(
				null,
				{ savedAt: "2026-02-01T00:00:00.000Z" },
				{
					jobId: "job-a",
					now: "2026-02-01T00:00:00.000Z",
					row: jobRow("job-a", { contentHash: "content-v1" }),
					snapshotAt: "2026-02-01T00:00:00.000Z",
				},
			),
			firstAbsentSnapshotAt: "2026-03-01T00:00:00.000Z",
		};

		const result = reconcileJobsLocalSnapshot({
			snapshot: {
				settings: DEFAULT_JOBS_LOCAL_SETTINGS,
				jobRecords: [staleSaved],
				savedSearches: [],
				retainedJobDetails: [],
			},
			rows: [jobRow("job-a", { contentHash: "content-v2" })],
			manifest: { ...manifest(1), snapshotAt: "2026-04-01T00:00:00.000Z" },
			complete: true,
			now: "2026-04-02T00:00:00.000Z",
		});

		expect(result?.jobRecords[0]).toMatchObject({
			jobId: "job-a",
			firstAbsentSnapshotAt: null,
			lastSeenSnapshotAt: "2026-04-01T00:00:00.000Z",
			lastKnownFingerprint: "content-v2",
		});
	});

	it("rejects oversized local import payloads before JSON parsing", () => {
		const oversized = JSON.stringify({
			source: "openopps.jobs.local",
			schemaVersion: 1,
			exportedAt: "2026-06-30T03:00:00.000Z",
			settings: DEFAULT_JOBS_LOCAL_SETTINGS,
			jobRecords: [],
			savedSearches: [],
			retainedJobDetails: [],
			// Limit is 32MB (JOBS_LOCAL_IMPORT_MAX_BYTES); pad past it.
			padding: "x".repeat(33 * 1024 * 1024),
		});
		const parsed = parseJobsLocalImport(oversized);
		expect(parsed.ok).toBe(false);
		if (!parsed.ok) {
			expect(parsed.errors[0]).toMatch(/32\s*MB|size limit/i);
		}
	});

	it("rejects local imports with too many records", () => {
		const parsed = parseJobsLocalImport({
			source: "openopps.jobs.local",
			schemaVersion: 1,
			exportedAt: "2026-06-30T03:00:00.000Z",
			settings: DEFAULT_JOBS_LOCAL_SETTINGS,
			jobRecords: Array.from({ length: 5_001 }, (_, index) => ({
				jobId: `job-${index}`,
				createdAt: "2026-06-30T03:00:00.000Z",
				updatedAt: "2026-06-30T03:00:00.000Z",
			})),
			savedSearches: [],
			retainedJobDetails: [],
		});
		expect(parsed.ok).toBe(false);
		if (!parsed.ok) {
			expect(parsed.errors[0]).toContain("5,000");
		}
	});

	it("sanitizes retained job detail imports with unsafe urls and forbidden fields", () => {
		const record = normalizeRetainedJobDetailRecord({
			jobId: "job-a",
			capturedAt: "2026-06-30T03:00:00.000Z",
			updatedAt: "2026-06-30T03:00:00.000Z",
			detail: {
				id: "job-a",
				status: "open",
				title: "Platform Engineer",
				company: "Acme Corp",
				applyUrl: "javascript:alert(1)",
				postingUrl: "https://example.com/jobs/1",
				descriptionHtml: '<img src=x onerror="alert(1)">',
				payloadSnapshots: [{ kind: "raw", payload: { secret: "nope" } }],
			},
		});

		expect(record?.detail.applyUrl).toBeNull();
		expect(record?.detail.postingUrl).toBe("https://example.com/jobs/1");
		expect(record?.detail.description).toBeNull();
		expect("descriptionHtml" in (record?.detail ?? {})).toBe(false);
		expect("payloadSnapshots" in (record?.detail ?? {})).toBe(false);

		const direct = createRetainedJobDetailRecord({
			row: null,
			detail: {
				id: "job-a",
				postingUrl: "javascript:alert(1)",
				descriptionHtml: "<p>private html</p>",
				payloadSnapshots: [{ secret: "nope" }],
			} as never,
			now: "2026-06-30T03:00:00.000Z",
		});
		expect(direct.detail.postingUrl).toBeNull();
		expect("descriptionHtml" in direct.detail).toBe(false);
		expect("payloadSnapshots" in direct.detail).toBe(false);
	});

	it("repairs malformed stored saved-search filters and mismatched retained ids", () => {
		const now = "2026-06-30T03:00:00.000Z";
		const search = normalizeSavedSearchRecord({
			id: "saved-a",
			filters: { ...DEFAULT_JOB_BOARD_FILTERS, query: 42, unknown: "drop" },
			createdAt: now,
			updatedAt: now,
		});

		expect(search?.filters).toEqual(DEFAULT_JOB_BOARD_FILTERS);
		expect(
			normalizeRetainedJobDetailRecord({
				jobId: "job-a",
				detail: { id: "job-b" },
			}),
		).toBeNull();
	});

	it("exports and imports only versioned local data envelopes", () => {
		const now = "2026-06-30T03:00:00.000Z";
		const snapshot: JobsLocalSnapshot = {
			settings: DEFAULT_JOBS_LOCAL_SETTINGS,
			jobRecords: [
				updateJobWorkflowRecord(null, { savedAt: now }, { jobId: "job-a", now }),
			],
			savedSearches: [
				createSavedSearchRecord({
					filters: DEFAULT_JOB_BOARD_FILTERS,
					rows: [jobRow("job-a")],
					sortKey: "latest",
					manifest: manifest(),
					now,
				}),
			],
			retainedJobDetails: [
				createRetainedJobDetailRecord({
					row: jobRow("job-a"),
					detail: {
						id: "job-a",
						title: "Platform Engineer",
						postingUrl: "https://example.com/jobs/job-a",
					},
					now,
				}),
			],
		};
		const envelope = createJobsLocalExportEnvelope(snapshot, now);
		const parsed = parseJobsLocalImport(JSON.stringify(envelope));

		expect(parsed.ok).toBe(true);
		if (parsed.ok) {
			expect(parsed.data.jobRecords).toHaveLength(1);
			expect(parsed.data.savedSearches).toHaveLength(1);
			expect(parsed.data.retainedJobDetails).toHaveLength(1);
		}
		expect(parseJobsLocalImport('{"source":"other"}').ok).toBe(false);
	});

	it("strictly migrates known schema-v1 fields without trusting unknown data", () => {
		const parsed = parseJobsLocalImport({
			source: "openopps.jobs.local",
			schemaVersion: 1,
			exportedAt: "2026-06-30T03:00:00.000Z",
			settings: { showHidden: true },
			jobRecords: [{ jobId: "job-a", notes: "legacy note" }],
			savedSearches: [
				{
					id: "search-legacy",
					filters: DEFAULT_JOB_BOARD_FILTERS,
				},
			],
			retainedJobDetails: [
				{
					jobId: "job-a",
					detail: { id: "job-a", title: "Legacy detail" },
				},
			],
		});

		expect(parsed.ok).toBe(true);
		if (parsed.ok) {
			expect(parsed.data.settings.showHidden).toBe(true);
			expect(parsed.data.jobRecords[0]?.notes).toBe("legacy note");
			expect(parsed.data.savedSearches[0]?.reviewStatus).toBe("needs-review");
			expect(parsed.data.retainedJobDetails[0]?.detail.title).toBe(
				"Legacy detail",
			);
		}
	});

	it("strictly rejects unexpected fields, duplicate ids, and private import data", () => {
		const now = "2026-06-30T03:00:00.000Z";
		const record = updateJobWorkflowRecord(
			null,
			{ savedAt: now },
			{ jobId: "job-a", now },
		);
		const base = createJobsLocalExportEnvelope(
			{
				settings: DEFAULT_JOBS_LOCAL_SETTINGS,
				jobRecords: [record],
				savedSearches: [],
				retainedJobDetails: [],
			},
			now,
		);

		expect(parseJobsLocalImport({ ...base, unexpected: true }).ok).toBe(false);
		expect(
			parseJobsLocalImport({ ...base, jobRecords: [record, record] }).ok,
		).toBe(false);
		expect(
			parseJobsLocalImport({
				...base,
				retainedJobDetails: [
					{
						schemaVersion: base.schemaVersion,
						jobId: "job-a",
						capturedAt: now,
						updatedAt: now,
						snapshotAt: null,
						rowSnapshot: null,
						detail: {
							id: "job-a",
							descriptionHtml: "<p>private raw html</p>",
						},
					},
				],
			}).ok,
		).toBe(false);
	});

	it("summarizes private local data without exposing note text", () => {
		const now = "2026-06-30T03:00:00.000Z";
		const noted = updateJobWorkflowRecord(
			null,
			{ notes: "private text", appliedAt: now },
			{ jobId: "job-a", now },
		);
		const hidden = updateJobWorkflowRecord(
			null,
			{ hiddenAt: now, viewedAt: now },
			{ jobId: "job-b", now },
		);
		const summary = summarizeJobsLocalData({
			settings: DEFAULT_JOBS_LOCAL_SETTINGS,
			jobRecords: [noted, hidden],
			savedSearches: [],
			retainedJobDetails: [],
		});

		expect(summary).toMatchObject({
			viewed: 1,
			hidden: 1,
			applied: 1,
			noted: 1,
		});
	});
});

function jobRow(
	id: string,
	values: Partial<Record<keyof typeof J, string | number | null>> = {},
): SearchRow {
	const row: SearchRow = new Array(J.payloadHash + 1).fill(null);
	row[J.id] = id;
	row[J.source] = "a16z";
	row[J.board] = "acme";
	row[J.provider] = "greenhouse";
	row[J.status] = "open";
	row[J.title] = "Platform Engineer";
	row[J.company] = "Acme Corp";
	row[J.latestObserved] = "2026-06-16T10:00:00Z";
	row[J.descriptionSnippet] = "Build reliable platform services.";
	row[J.syncedAt] = "2026-06-16T10:00:00Z";
	for (const [key, value] of Object.entries(values)) {
		row[J[key as keyof typeof J]] = value;
	}
	return row;
}

function manifest(jobCount = 0): SearchManifest {
	return {
		version: 4,
		snapshotAt: "2026-06-16T00:00:00.000Z",
		source: { database: "kaggle/openoppsdb.sqlite", tables: [] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { columns: [], count: jobCount },
			boards: { columns: [], count: 0 },
			providers: { columns: [], count: 0 },
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: [],
			supportLevels: [],
			routeStatuses: [],
			workplaces: [],
			employmentTypes: [],
		},
	};
}

function memoryStorage(initial: Record<string, string> = {}) {
	const values = new Map(Object.entries(initial));
	return {
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => values.set(key, value),
		removeItem: (key: string) => values.delete(key),
	};
}
