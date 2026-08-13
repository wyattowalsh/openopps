"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import {
	clearIndexedJobsLocalData,
	deleteStoreRecord,
	hasBrowserIndexedDb,
	importIndexedSnapshot,
	jobsLocalStoreNames,
	readIndexedJobsLocalSnapshot,
	readJobsLocalSettings,
	removeJobsLocalSettings,
	replaceIndexedSnapshot,
	writeJobsLocalSettings,
	writeJobWorkflowTransaction,
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
	normalizeSavedSearchRecord,
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

type LocalMutationResult<T> = {
	snapshot: JobsLocalSnapshot;
	value: T;
	changed?: boolean;
	committed?: boolean;
};

function formatStorageError(caught: unknown) {
	return caught instanceof Error && caught.message.trim()
		? caught.message
		: "Local jobs data could not be saved. Your previous data is unchanged.";
}

function snapshotWithSettings(
	snapshot: JobsLocalSnapshot,
	settings: JobsLocalSettings,
): JobsLocalSnapshot {
	return { ...snapshot, settings };
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
	const [storageError, setStorageError] = useState<string | null>(null);
	const snapshotRef = useRef<JobsLocalSnapshot>({
		settings,
		jobRecords: [],
		savedSearches: [],
		retainedJobDetails: [],
	});
	const mutationTailRef = useRef<Promise<void>>(Promise.resolve());

	const applyVisibleSnapshot = useCallback((next: JobsLocalSnapshot) => {
		const committed = cloneLocalSnapshot(next);
		snapshotRef.current = committed;
		setSettingsState(committed.settings);
		setJobRecords(indexByJobId(committed.jobRecords));
		setSavedSearches(committed.savedSearches);
		setRetainedJobDetails(indexByJobId(committed.retainedJobDetails));
	}, []);

	const enqueueLocalMutation = useCallback(
		<T,>(
			operation: (current: JobsLocalSnapshot) => Promise<LocalMutationResult<T>>,
		): Promise<T> => {
			const execute = () => operation(snapshotRef.current);
			const pending = mutationTailRef.current.then(execute, execute).then(
				(result) => {
					if (result.changed !== false) {
						applyVisibleSnapshot(result.snapshot);
					}
					if (result.committed !== false) {
						setStorageStatus(hasBrowserIndexedDb() ? "available" : "unavailable");
						setStorageError(null);
					}
					return result.value;
				},
				(caught) => {
					setStorageStatus("error");
					setStorageError(formatStorageError(caught));
					throw caught;
				},
			);
			mutationTailRef.current = pending.then(
				() => undefined,
				() => undefined,
			);
			return pending;
		},
		[applyVisibleSnapshot],
	);

	useEffect(() => {
		let mounted = true;
		const load = async () => {
			try {
				const indexed = await readIndexedJobsLocalSnapshot();
				if (!mounted) {
					return;
				}
				const next = { ...indexed, settings: snapshotRef.current.settings };
				applyVisibleSnapshot(next);
				setStorageStatus(hasBrowserIndexedDb() ? "available" : "unavailable");
				setStorageError(null);
			} catch (caught) {
				if (mounted) {
					setStorageStatus("error");
					setStorageError(formatStorageError(caught));
				}
			}
		};
		const pendingLoad = mutationTailRef.current.then(load, load);
		mutationTailRef.current = pendingLoad.then(
			() => undefined,
			() => undefined,
		);
		return () => {
			mounted = false;
		};
	}, [applyVisibleSnapshot]);

	const setSettings = useCallback(
		(patch: Partial<JobsLocalSettings>) => {
			void enqueueLocalMutation(async (current) => {
				const nextSettings = normalizeJobsLocalSettings({
					...current.settings,
					...patch,
				});
				writeJobsLocalSettings(nextSettings);
				return {
					snapshot: snapshotWithSettings(current, nextSettings),
					value: undefined,
				};
			}).catch(() => undefined);
		},
		[enqueueLocalMutation],
	);

	const upsertJobRecord = useCallback(
		(
			jobId: string,
			updater: (
				record: JobWorkflowRecord | null,
				now: string,
			) => JobWorkflowRecord,
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
			void enqueueLocalMutation(async (current) => {
				const now = new Date().toISOString();
				const jobsById = indexByJobId(current.jobRecords);
				const detailsById = indexByJobId(current.retainedJobDetails);
				const nextRecord = updater(jobsById[normalizedJobId] ?? null, now);
				let retainedDetail: RetainedJobDetailRecord | null | undefined;

				if (
					options.detail?.id === normalizedJobId &&
					shouldRetainJobDetail(nextRecord)
				) {
					retainedDetail = createRetainedJobDetailRecord({
						row: options.row ?? null,
						detail: options.detail,
						now,
						snapshotAt: options.snapshotAt ?? null,
					});
				} else if (!shouldRetainJobDetail(nextRecord)) {
					retainedDetail = null;
				}

				await writeJobWorkflowTransaction({
					record: nextRecord,
					retainedDetail,
				});
				jobsById[normalizedJobId] = nextRecord;
				if (retainedDetail === null) {
					delete detailsById[normalizedJobId];
				} else if (retainedDetail) {
					detailsById[normalizedJobId] = retainedDetail;
				}
				return {
					snapshot: {
						...current,
						jobRecords: Object.values(jobsById),
						retainedJobDetails: Object.values(detailsById),
					},
					value: undefined,
				};
			}).catch(() => undefined);
		},
		[enqueueLocalMutation],
	);

	const markViewed = useCallback(
		(jobId: string, row: SearchRow | null, snapshotAt: string | null) => {
			upsertJobRecord(
				jobId,
				(record, now) =>
					updateJobWorkflowRecord(
						record,
						record?.viewedAt ? {} : { viewedAt: now },
						{ jobId, now, row, snapshotAt },
					),
				{ row, snapshotAt },
			);
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
		(
			jobId: string,
			row: SearchRow | null,
			detail: JobDetail,
			snapshotAt: string | null,
		) => {
			const normalizedJobId = jobId.trim();
			if (!normalizedJobId || detail.id !== normalizedJobId) {
				return;
			}
			void enqueueLocalMutation(async (current) => {
				const record = indexByJobId(current.jobRecords)[normalizedJobId];
				if (!shouldRetainJobDetail(record)) {
					return {
						snapshot: current,
						value: undefined,
						changed: false,
						committed: false,
					};
				}
				const retained = createRetainedJobDetailRecord({
					row,
					detail,
					now: new Date().toISOString(),
					snapshotAt,
				});
				await writeStoreRecord(jobsLocalStoreNames.retainedJobDetails, retained);
				const detailsById = indexByJobId(current.retainedJobDetails);
				detailsById[normalizedJobId] = retained;
				return {
					snapshot: {
						...current,
						retainedJobDetails: Object.values(detailsById),
					},
					value: undefined,
				};
			}).catch(() => undefined);
		},
		[enqueueLocalMutation],
	);

	const createSavedSearch = useCallback(
		(
			{
				filters,
				rows,
				baseline,
				baselineScope,
				baselineTotalMatches,
				reviewStatus,
				reviewCursor,
				sortKey,
				manifest,
			}: {
				filters: JobBoardFilters;
				rows: SearchRow[];
				baseline?: SavedSearchRecord["baseline"];
				baselineScope?: SavedSearchRecord["baselineScope"];
				baselineTotalMatches?: number | null;
				reviewStatus?: SavedSearchRecord["reviewStatus"];
				reviewCursor?: SavedSearchRecord["reviewCursor"];
				sortKey: JobSortKey;
				manifest: SearchManifest | null;
			},
		) =>
			enqueueLocalMutation(async (current) => {
				const record = createSavedSearchRecord({
					filters,
					rows,
					baseline,
					baselineScope,
					baselineTotalMatches,
					reviewStatus,
					reviewCursor,
					sortKey,
					manifest,
					now: new Date().toISOString(),
				});
				await writeStoreRecord(jobsLocalStoreNames.savedSearches, record);
				return {
					snapshot: {
						...current,
						savedSearches: [...current.savedSearches, record],
					},
					value: record,
				};
			}),
		[enqueueLocalMutation],
	);

	const updateSavedSearch = useCallback(
		(record: SavedSearchRecord) =>
			enqueueLocalMutation(async (current) => {
				const now = new Date().toISOString();
				const next = normalizeSavedSearchRecord(
					{ ...record, updatedAt: now },
					now,
				);
				if (!next) {
					throw new Error("The saved search is invalid and was not changed.");
				}
				await writeStoreRecord(jobsLocalStoreNames.savedSearches, next);
				return {
					snapshot: {
						...current,
						savedSearches: current.savedSearches.map((candidate) =>
							candidate.id === next.id ? next : candidate,
						),
					},
					value: undefined,
				};
			}),
		[enqueueLocalMutation],
	);

	const deleteSavedSearch = useCallback(
		(id: string) =>
			enqueueLocalMutation(async (current) => {
				await deleteStoreRecord(jobsLocalStoreNames.savedSearches, id);
				return {
					snapshot: {
						...current,
						savedSearches: current.savedSearches.filter(
							(record) => record.id !== id,
						),
					},
					value: undefined,
				};
			}),
		[enqueueLocalMutation],
	);

	const duplicateSavedSearch = useCallback(
		(record: SavedSearchRecord) => {
			void enqueueLocalMutation(async (current) => {
				const duplicate = duplicateSavedSearchRecord(record);
				await writeStoreRecord(jobsLocalStoreNames.savedSearches, duplicate);
				return {
					snapshot: {
						...current,
						savedSearches: [...current.savedSearches, duplicate],
					},
					value: undefined,
				};
			}).catch(() => undefined);
		},
		[enqueueLocalMutation],
	);

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
			const baselineScope = options.baselineScope ?? "page";
			return updateSavedSearch({
				...record,
				lastReviewedAt: now,
				lastOpenedAt: now,
				manifestVersion: manifest?.version ?? record.manifestVersion,
				snapshotAt: manifest?.snapshotAt ?? record.snapshotAt,
				baselineScope,
				baselineTotalMatches:
					baselineScope === "full"
						? options.baselineTotalMatches ??
							options.baseline?.reviewedJobIds.length ??
							rows.length
						: options.baselineTotalMatches ?? null,
				reviewStatus: "current",
				reviewCursor: {
					semantics: "first-seen-v1",
					reviewedAt: now,
					snapshotAt: manifest?.snapshotAt ?? record.snapshotAt,
				},
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
			try {
				await enqueueLocalMutation(async (current) => {
					let next: JobsLocalSnapshot;
					if (category === "all") {
						next = {
							settings: { ...DEFAULT_JOBS_LOCAL_SETTINGS },
							jobRecords: [],
							savedSearches: [],
							retainedJobDetails: [],
						};
					} else if (category === "savedSearches") {
						next = { ...current, savedSearches: [] };
					} else if (category === "details") {
						next = { ...current, retainedJobDetails: [] };
					} else {
						const now = new Date().toISOString();
						const nextRecords = Object.fromEntries(
							current.jobRecords.map((record) => [
								record.jobId,
								updateJobWorkflowRecord(
									record,
									clearPatchForCategory(category),
									{ jobId: record.jobId, now },
								),
							]),
						);
						const pruned = pruneRetainedJobDetailsForWorkflowRecords({
							jobRecords: nextRecords,
							retainedJobDetails: indexByJobId(current.retainedJobDetails),
						});
						next = {
							...current,
							jobRecords: Object.values(nextRecords),
							retainedJobDetails: Object.values(pruned.retained),
						};
					}

					if (category === "all") {
						removeJobsLocalSettings();
					}
					try {
						if (category === "all") {
							await clearIndexedJobsLocalData();
						} else {
							await replaceIndexedSnapshot(next);
						}
					} catch (caught) {
						if (category === "all") {
							writeJobsLocalSettings(current.settings);
						}
						throw caught;
					}
					return { snapshot: next, value: undefined };
				});
			} catch {
				// The queue records the actionable error while keeping prior visible state.
			}
		},
		[enqueueLocalMutation],
	);

	const exportLocalData = useCallback(
		() =>
			JSON.stringify(
				createJobsLocalExportEnvelope(snapshotRef.current),
				null,
				2,
			),
		[],
	);

	const importLocalData = useCallback(
		async (raw: string, mode: "merge" | "replace") => {
			const parsed = parseJobsLocalImport(raw);
			if (!parsed.ok) {
				return parsed;
			}
			try {
				return await enqueueLocalMutation(async (current) => {
					const imported: JobsLocalSnapshot = {
						settings: parsed.data.settings,
						jobRecords: parsed.data.jobRecords,
						savedSearches: parsed.data.savedSearches,
						retainedJobDetails: parsed.data.retainedJobDetails,
					};
					const next =
						mode === "replace"
							? imported
							: mergeJobsLocalSnapshots(current, imported);
					writeJobsLocalSettings(next.settings);
					try {
						await importIndexedSnapshot({ next, current, mode });
					} catch (caught) {
						writeJobsLocalSettings(current.settings);
						throw caught;
					}
					return {
						snapshot: next,
						value: {
							ok: true as const,
							data: createJobsLocalExportEnvelope(next),
						},
					};
				});
			} catch (caught) {
				return { ok: false as const, errors: [formatStorageError(caught)] };
			}
		},
		[enqueueLocalMutation],
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
		async (
			rows: SearchRow[],
			manifest: SearchManifest | null,
			complete = false,
		) => {
			try {
				return await enqueueLocalMutation(async (current) => {
					const result = reconcileJobsLocalSnapshot({
						snapshot: current,
						rows,
						manifest,
						complete,
					});
					if (!result) {
						return {
							snapshot: current,
							value: false,
							changed: false,
							committed: false,
						};
					}
					const next = {
						...current,
						jobRecords: result.jobRecords,
						retainedJobDetails: result.retainedJobDetails,
					};
					await replaceIndexedSnapshot(next);
					return { snapshot: next, value: true };
				});
			} catch {
				return false;
			}
		},
		[enqueueLocalMutation],
	);

	return {
		settings,
		setSettings,
		jobRecords,
		savedSearches,
		retainedJobDetails,
		storageStatus,
		storageError,
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

function cloneLocalSnapshot(snapshot: JobsLocalSnapshot): JobsLocalSnapshot {
	if (typeof structuredClone === "function") {
		return structuredClone(snapshot);
	}
	return JSON.parse(JSON.stringify(snapshot)) as JobsLocalSnapshot;
}
