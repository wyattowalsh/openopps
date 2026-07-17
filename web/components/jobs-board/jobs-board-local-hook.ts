"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
import {
	clearIndexedJobsLocalData,
	clearStore,
	deleteStoreRecord,
	hasBrowserIndexedDb,
	jobsLocalStoreNames,
	readIndexedJobsLocalSnapshot,
	readJobsLocalSettings,
	removeJobsLocalSettings,
	writeIndexedSnapshot,
	writeJobsLocalSettings,
	writeStoreRecord,
} from "@/components/jobs-board/jobs-board-local-idb";
import {
	baselineFromRows,
	clearPatchForCategory,
	createJobsLocalExportEnvelope,
	createRetainedJobDetailRecord,
	createSavedSearchRecord,
	duplicateSavedSearchRecord,
	indexByJobId,
	mergeJobsLocalSnapshots,
	normalizeJobsLocalSettings,
	parseJobsLocalImport,
	pruneRetainedJobDetailsForWorkflowRecords,
	reconcileJobsLocalSnapshot,
	shouldRetainJobDetail,
	summarizeJobsLocalData,
	updateJobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-reconcile";
import {
	DEFAULT_JOBS_LOCAL_SETTINGS,
	type JobWorkflowRecord,
	type JobsLocalSettings,
	type JobsLocalSnapshot,
	type JobsLocalStorageStatus,
	type RetainedJobDetailRecord,
	type SavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-types";
import type {
	JobDetail,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";

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
				void writeStoreRecord(jobsLocalStoreNames.jobRecords, nextRecord);
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
					void writeStoreRecord(jobsLocalStoreNames.retainedJobDetails, retained);
					setRetainedJobDetails((details) => ({
						...details,
						[normalizedJobId]: retained,
					}));
				} else if (!shouldRetainJobDetail(nextRecord)) {
					void deleteStoreRecord(
						jobsLocalStoreNames.retainedJobDetails,
						normalizedJobId,
					);
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
			void writeStoreRecord(jobsLocalStoreNames.retainedJobDetails, retained);
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
			void writeStoreRecord(jobsLocalStoreNames.savedSearches, record);
		},
		[],
	);

	const updateSavedSearch = useCallback((record: SavedSearchRecord) => {
		const next = { ...record, updatedAt: new Date().toISOString() };
		setSavedSearches((current) =>
			current.map((candidate) => (candidate.id === next.id ? next : candidate)),
		);
		void writeStoreRecord(jobsLocalStoreNames.savedSearches, next);
	}, []);

	const deleteSavedSearch = useCallback((id: string) => {
		setSavedSearches((current) => current.filter((record) => record.id !== id));
		void deleteStoreRecord(jobsLocalStoreNames.savedSearches, id);
	}, []);

	const duplicateSavedSearch = useCallback((record: SavedSearchRecord) => {
		const duplicate = duplicateSavedSearchRecord(record);
		setSavedSearches((current) => [...current, duplicate]);
		void writeStoreRecord(jobsLocalStoreNames.savedSearches, duplicate);
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
				await clearStore(jobsLocalStoreNames.savedSearches);
				return;
			}
			if (category === "details") {
				setRetainedJobDetails({});
				await clearStore(jobsLocalStoreNames.retainedJobDetails);
				return;
			}
			setJobRecords((current) => {
				const now = new Date().toISOString();
				const next: Record<string, JobWorkflowRecord> = {};
				for (const [jobId, record] of Object.entries(current)) {
					const patch = clearPatchForCategory(category);
					const nextRecord = updateJobWorkflowRecord(record, patch, { jobId, now });
					next[jobId] = nextRecord;
					void writeStoreRecord(jobsLocalStoreNames.jobRecords, nextRecord);
				}
				const pruned = pruneRetainedJobDetailsForWorkflowRecords({
					jobRecords: next,
					retainedJobDetails,
				});
				if (pruned.prunedJobIds.length > 0) {
					setRetainedJobDetails(pruned.retained);
					for (const jobId of pruned.prunedJobIds) {
						void deleteStoreRecord(jobsLocalStoreNames.retainedJobDetails, jobId);
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

	const importLocalData = useCallback(
		async (raw: string, mode: "merge" | "replace") => {
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
		},
		[jobRecords, retainedJobDetails, savedSearches, settings],
	);

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
				void writeStoreRecord(jobsLocalStoreNames.jobRecords, record);
			}
			for (const jobId of result.prunedRetainedJobIds) {
				void deleteStoreRecord(jobsLocalStoreNames.retainedJobDetails, jobId);
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