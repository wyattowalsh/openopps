import {
	JOBS_LOCAL_DB_NAME,
	JOBS_LOCAL_DB_VERSION,
	JOBS_LOCAL_SETTINGS_KEY,
	type JobWorkflowRecord,
	type JobsLocalExportEnvelope,
	type JobsLocalSettings,
	type JobsLocalSnapshot,
	type RetainedJobDetailRecord,
	type SavedSearchRecord,
	DEFAULT_JOBS_LOCAL_SETTINGS,
	type JobsLocalIndexedSnapshot,
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

type KeyValueStorage = Pick<Storage, "getItem" | "removeItem" | "setItem">;

let dbPromise: Promise<IDBDatabase | null> | null = null;

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

export async function readIndexedJobsLocalSnapshot(): Promise<JobsLocalIndexedSnapshot> {
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

export async function writeIndexedSnapshot(
	snapshot: JobsLocalSnapshot | JobsLocalExportEnvelope,
) {
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

export async function clearIndexedJobsLocalData() {
	await Promise.all([
		clearStore(JOB_RECORD_STORE),
		clearStore(SAVED_SEARCH_STORE),
		clearStore(RETAINED_DETAIL_STORE),
	]);
}

export async function writeStoreRecord(storeName: string, value: unknown) {
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

export async function deleteStoreRecord(storeName: string, key: string) {
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

export async function clearStore(storeName: string) {
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

export const jobsLocalStoreNames = {
	jobRecords: JOB_RECORD_STORE,
	savedSearches: SAVED_SEARCH_STORE,
	retainedJobDetails: RETAINED_DETAIL_STORE,
} as const;

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