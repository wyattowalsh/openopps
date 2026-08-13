import {
	JOBS_LOCAL_DB_NAME,
	JOBS_LOCAL_DB_VERSION,
	JOBS_LOCAL_IMPORT_BACKUP_LIMIT,
	JOBS_LOCAL_IMPORT_MAX_BYTES,
	JOBS_LOCAL_IMPORT_MAX_RECORDS,
	JOBS_LOCAL_SETTINGS_KEY,
	type JobWorkflowRecord,
	type JobsLocalExportEnvelope,
	type JobsLocalSettings,
	type JobsLocalSnapshot,
	type RetainedJobDetailRecord,
	type SavedSearchRecord,
	DEFAULT_JOBS_LOCAL_SETTINGS,
	type JobsLocalIndexedSnapshot,
	type JobsLocalImportBackup,
} from "@/components/jobs-board/jobs-board-local-types";
import {
	normalizeJobWorkflowRecord,
	normalizeJobsLocalSettings,
	normalizeRetainedJobDetailRecord,
	normalizeSavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-reconcile";

const JOB_RECORD_STORE = "jobRecords";
const SAVED_SEARCH_STORE = "savedSearches";
const RETAINED_DETAIL_STORE = "retainedJobDetails";
const IMPORT_BACKUP_STORE = "importBackups";

type KeyValueStorage = Pick<Storage, "getItem" | "removeItem" | "setItem">;

let dbPromise: Promise<IDBDatabase | null> | null = null;
let mutationTail: Promise<void> = Promise.resolve();

function browserLocalStorage() {
	return typeof window === "undefined" ? undefined : window.localStorage;
}

export function hasBrowserIndexedDb() {
	return typeof indexedDB !== "undefined";
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

function isPresent<T>(value: T | null | undefined): value is T {
	return value !== null && value !== undefined;
}

async function openJobsLocalDatabase() {
	if (dbPromise) {
		return dbPromise;
	}
	if (!hasBrowserIndexedDb()) {
		return null;
	}
	dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
		const request = indexedDB.open(JOBS_LOCAL_DB_NAME, JOBS_LOCAL_DB_VERSION);
		let settled = false;
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
			if (!db.objectStoreNames.contains(IMPORT_BACKUP_STORE)) {
				db.createObjectStore(IMPORT_BACKUP_STORE, { keyPath: "id" });
			}
		};
		request.onsuccess = () => {
			if (settled) {
				request.result.close();
				return;
			}
			settled = true;
			const db = request.result;
			db.onversionchange = () => {
				db.close();
				dbPromise = null;
			};
			resolve(db);
		};
		request.onerror = () => {
			if (!settled) {
				settled = true;
				reject(request.error ?? new Error("Unable to open local jobs storage."));
			}
		};
		request.onblocked = () => {
			if (!settled) {
				settled = true;
				reject(new Error("Local jobs storage upgrade is blocked by another tab."));
			}
		};
	}).catch((error) => {
		dbPromise = null;
		throw error;
	});
	return dbPromise;
}

export async function readIndexedJobsLocalSnapshot(): Promise<JobsLocalIndexedSnapshot> {
	return enqueueIndexedMutation(async () => {
		const { jobRecords, savedSearches, retainedJobDetails } =
			await readIndexedSnapshotUnqueued();
		return {
			jobRecords: jobRecords
				.map((record) => normalizeJobWorkflowRecord(record))
				.filter(isPresent),
			savedSearches: savedSearches
				.map((record) => normalizeSavedSearchRecord(record))
				.filter(isPresent),
			retainedJobDetails: retainedJobDetails
				.map((record) => normalizeRetainedJobDetailRecord(record))
				.filter(isPresent),
		};
	});
}

export async function writeIndexedSnapshot(
	snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope,
) {
	const captured = cloneForIndexedDb(snapshot);
	await enqueueIndexedMutation(() => runIndexedSnapshotTransaction(captured, false));
}

export async function replaceIndexedSnapshot(
	snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope,
) {
	const captured = cloneForIndexedDb(snapshot);
	await enqueueIndexedMutation(() => runIndexedSnapshotTransaction(captured, true));
}

export async function clearIndexedJobsLocalData() {
	await enqueueIndexedMutation(clearIndexedJobsLocalDataUnqueued);
}

export async function writeStoreRecord(storeName: string, value: unknown) {
	const captured = cloneForIndexedDb(value);
	await enqueueIndexedMutation(() => writeStoreRecordUnqueued(storeName, captured));
}

export async function deleteStoreRecord(storeName: string, key: string) {
	await enqueueIndexedMutation(() => deleteStoreRecordUnqueued(storeName, key));
}

export async function clearStore(storeName: string) {
	await enqueueIndexedMutation(() => clearStoreUnqueued(storeName));
}

export async function writeJobWorkflowTransaction({
	record,
	retainedDetail,
}: {
	record: JobWorkflowRecord;
	retainedDetail?: RetainedJobDetailRecord | null;
}) {
	const capturedRecord = cloneForIndexedDb(record);
	const capturedDetail = cloneForIndexedDb(retainedDetail);
	await enqueueIndexedMutation(async () => {
		const db = await requireJobsLocalDatabase();
		await runTransaction(
			db.transaction([JOB_RECORD_STORE, RETAINED_DETAIL_STORE], "readwrite"),
			(transaction) => {
				transaction.objectStore(JOB_RECORD_STORE).put(capturedRecord);
				if (capturedDetail === null) {
					transaction.objectStore(RETAINED_DETAIL_STORE).delete(capturedRecord.jobId);
				} else if (capturedDetail) {
					transaction.objectStore(RETAINED_DETAIL_STORE).put(capturedDetail);
				}
			},
		);
	});
}

export async function importIndexedSnapshot({
	next,
	current,
	mode,
	createdAt = new Date().toISOString(),
}: {
	next: JobsLocalSnapshot | JobsLocalExportEnvelope;
	current: JobsLocalSnapshot;
	mode: "merge" | "replace";
	createdAt?: string;
}) {
	const capturedNext = cloneForIndexedDb(next);
	const backup = createImportBackup(current, mode, createdAt);
	await enqueueIndexedMutation(() =>
		runImportSnapshotTransaction(capturedNext, backup),
	);
}

export async function readIndexedJobsLocalBackups() {
	return enqueueIndexedMutation(() =>
		readAllFromStore<JobsLocalImportBackup>(IMPORT_BACKUP_STORE),
	);
}

export async function flushJobsLocalMutationsForTests() {
	await mutationTail;
}

function enqueueIndexedMutation<T>(operation: () => Promise<T>): Promise<T> {
	const result = mutationTail.then(operation, operation);
	mutationTail = result.then(
		() => undefined,
		() => undefined,
	);
	return result;
}

async function clearIndexedJobsLocalDataUnqueued() {
	const db = await requireJobsLocalDatabase();
	await runTransaction(
		db.transaction(
			[
				JOB_RECORD_STORE,
				SAVED_SEARCH_STORE,
				RETAINED_DETAIL_STORE,
				IMPORT_BACKUP_STORE,
			],
			"readwrite",
		),
		(transaction) => {
			transaction.objectStore(JOB_RECORD_STORE).clear();
			transaction.objectStore(SAVED_SEARCH_STORE).clear();
			transaction.objectStore(RETAINED_DETAIL_STORE).clear();
			transaction.objectStore(IMPORT_BACKUP_STORE).clear();
		},
	);
}

async function writeStoreRecordUnqueued(storeName: string, value: unknown) {
	const db = await requireJobsLocalDatabase();
	await runTransaction(db.transaction(storeName, "readwrite"), (transaction) => {
		transaction.objectStore(storeName).put(value);
	});
}

async function deleteStoreRecordUnqueued(storeName: string, key: string) {
	const db = await requireJobsLocalDatabase();
	await runTransaction(db.transaction(storeName, "readwrite"), (transaction) => {
		transaction.objectStore(storeName).delete(key);
	});
}

async function clearStoreUnqueued(storeName: string) {
	const db = await requireJobsLocalDatabase();
	await runTransaction(db.transaction(storeName, "readwrite"), (transaction) => {
		transaction.objectStore(storeName).clear();
	});
}

export const jobsLocalStoreNames = {
	jobRecords: JOB_RECORD_STORE,
	savedSearches: SAVED_SEARCH_STORE,
	retainedJobDetails: RETAINED_DETAIL_STORE,
	importBackups: IMPORT_BACKUP_STORE,
} as const;

async function readIndexedSnapshotUnqueued(): Promise<{
	jobRecords: JobWorkflowRecord[];
	savedSearches: SavedSearchRecord[];
	retainedJobDetails: RetainedJobDetailRecord[];
}> {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return { jobRecords: [], savedSearches: [], retainedJobDetails: [] };
	}
	return new Promise((resolve, reject) => {
		const transaction = db.transaction(
			[JOB_RECORD_STORE, SAVED_SEARCH_STORE, RETAINED_DETAIL_STORE],
			"readonly",
		);
		const jobsRequest = transaction.objectStore(JOB_RECORD_STORE).getAll();
		const searchesRequest = transaction.objectStore(SAVED_SEARCH_STORE).getAll();
		const detailsRequest = transaction.objectStore(RETAINED_DETAIL_STORE).getAll();
		const abort = () => transaction.abort();
		jobsRequest.onerror = abort;
		searchesRequest.onerror = abort;
		detailsRequest.onerror = abort;
		transaction.oncomplete = () =>
			resolve({
				jobRecords: jobsRequest.result as JobWorkflowRecord[],
				savedSearches: searchesRequest.result as SavedSearchRecord[],
				retainedJobDetails: detailsRequest.result as RetainedJobDetailRecord[],
			});
		transaction.onerror = () =>
			reject(
				transaction.error ??
					jobsRequest.error ??
					searchesRequest.error ??
					detailsRequest.error,
			);
		transaction.onabort = transaction.onerror;
	});
}

async function readAllFromStore<T>(storeName: string): Promise<T[]> {
	const db = await openJobsLocalDatabase();
	if (!db) {
		return [];
	}
	return new Promise((resolve, reject) => {
		const transaction = db.transaction(storeName, "readonly");
		const request = transaction.objectStore(storeName).getAll();
		let result: T[] = [];
		request.onsuccess = () => {
			result = request.result as T[];
		};
		request.onerror = () => transaction.abort();
		transaction.oncomplete = () => resolve(result);
		transaction.onerror = () => reject(transaction.error ?? request.error);
		transaction.onabort = () => reject(transaction.error ?? request.error);
	});
}

async function runIndexedSnapshotTransaction(
	snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope,
	replace: boolean,
) {
	const db = await requireJobsLocalDatabase();
	await runTransaction(
		db.transaction(
			[JOB_RECORD_STORE, SAVED_SEARCH_STORE, RETAINED_DETAIL_STORE],
			"readwrite",
		),
		(transaction) => {
			const jobs = transaction.objectStore(JOB_RECORD_STORE);
			const searches = transaction.objectStore(SAVED_SEARCH_STORE);
			const details = transaction.objectStore(RETAINED_DETAIL_STORE);
			if (replace) {
				jobs.clear();
				searches.clear();
				details.clear();
			}
			for (const record of snapshot.jobRecords) {
				jobs.put(record);
			}
			for (const record of snapshot.savedSearches) {
				searches.put(record);
			}
			for (const record of snapshot.retainedJobDetails) {
				details.put(record);
			}
		},
	);
}

async function runImportSnapshotTransaction(
	snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope,
	backup: JobsLocalImportBackup,
) {
	const db = await requireJobsLocalDatabase();
	await runTransaction(
		db.transaction(
			[
				JOB_RECORD_STORE,
				SAVED_SEARCH_STORE,
				RETAINED_DETAIL_STORE,
				IMPORT_BACKUP_STORE,
			],
			"readwrite",
		),
		(transaction) => {
			const jobs = transaction.objectStore(JOB_RECORD_STORE);
			const searches = transaction.objectStore(SAVED_SEARCH_STORE);
			const details = transaction.objectStore(RETAINED_DETAIL_STORE);
			const backups = transaction.objectStore(IMPORT_BACKUP_STORE);

			jobs.clear();
			searches.clear();
			details.clear();
			for (const record of snapshot.jobRecords) {
				jobs.put(record);
			}
			for (const record of snapshot.savedSearches) {
				searches.put(record);
			}
			for (const record of snapshot.retainedJobDetails) {
				details.put(record);
			}

			backups.put(backup);
			const allBackups = backups.getAll();
			allBackups.onerror = () => transaction.abort();
			allBackups.onsuccess = () => {
				const ordered = (allBackups.result as JobsLocalImportBackup[])
					.slice()
					.sort((left, right) =>
						left.createdAt === right.createdAt
							? right.id.localeCompare(left.id)
							: right.createdAt.localeCompare(left.createdAt),
					);
				for (const stale of ordered.slice(JOBS_LOCAL_IMPORT_BACKUP_LIMIT)) {
					backups.delete(stale.id);
				}
			};
		},
	);
}

function createImportBackup(
	snapshot: JobsLocalSnapshot,
	mode: "merge" | "replace",
	createdAt: string,
): JobsLocalImportBackup {
	const recordCount =
		snapshot.jobRecords.length +
		snapshot.savedSearches.length +
		snapshot.retainedJobDetails.length;
	if (recordCount > JOBS_LOCAL_IMPORT_MAX_RECORDS) {
		throw new Error(
			`Current local data exceeds the ${JOBS_LOCAL_IMPORT_MAX_RECORDS.toLocaleString()} record backup limit.`,
		);
	}
	const serialized = JSON.stringify(snapshot);
	const bytes = new TextEncoder().encode(serialized).byteLength;
	if (bytes > JOBS_LOCAL_IMPORT_MAX_BYTES) {
		throw new Error("Current local data exceeds the pre-import backup size limit.");
	}
	const entropy =
		typeof crypto !== "undefined" && "randomUUID" in crypto
			? crypto.randomUUID()
			: Math.random().toString(36).slice(2);
	return {
		id: `backup_${createdAt.replace(/[^0-9]/g, "")}_${entropy}`,
		createdAt,
		mode,
		bytes,
		snapshot: JSON.parse(serialized) as JobsLocalSnapshot,
	};
}

function cloneForIndexedDb<T>(value: T): T {
	if (value === undefined) {
		return value;
	}
	if (typeof structuredClone === "function") {
		return structuredClone(value);
	}
	return JSON.parse(JSON.stringify(value)) as T;
}

function runTransaction(
	transaction: IDBTransaction,
	mutate: (transaction: IDBTransaction) => void,
) {
	return new Promise<void>((resolve, reject) => {
		let settled = false;
		const fail = () => {
			if (!settled) {
				settled = true;
				reject(transaction.error ?? new Error("Local jobs storage transaction failed."));
			}
		};
		transaction.oncomplete = () => {
			if (!settled) {
				settled = true;
				resolve();
			}
		};
		transaction.onerror = fail;
		transaction.onabort = fail;
		try {
			mutate(transaction);
		} catch (caught) {
			try {
				transaction.abort();
			} finally {
				if (!settled) {
					settled = true;
					reject(caught);
				}
			}
		}
	});
}

export function resetJobsLocalDatabaseForTests() {
	dbPromise = null;
	mutationTail = Promise.resolve();
}

export function setJobsLocalDatabaseForTests(database: IDBDatabase | null) {
	dbPromise = Promise.resolve(database);
	mutationTail = Promise.resolve();
}

async function requireJobsLocalDatabase() {
	const db = await openJobsLocalDatabase();
	if (!db) {
		throw new Error("IndexedDB is unavailable; local jobs data was not changed.");
	}
	return db;
}
