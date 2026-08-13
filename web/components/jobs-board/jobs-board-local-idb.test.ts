import { afterEach, describe, expect, it } from "vitest";

import {
	clearIndexedJobsLocalData,
	DEFAULT_JOBS_LOCAL_SETTINGS,
	flushJobsLocalMutationsForTests,
	importIndexedSnapshot,
	jobsLocalStoreNames,
	readIndexedJobsLocalBackups,
	readIndexedJobsLocalSnapshot,
	resetJobsLocalDatabaseForTests,
	setJobsLocalDatabaseForTests,
	updateJobWorkflowRecord,
	writeJobWorkflowTransaction,
	writeStoreRecord,
	type JobsLocalSnapshot,
} from "@/components/jobs-board/jobs-board-local-state";

afterEach(async () => {
	await flushJobsLocalMutationsForTests();
	resetJobsLocalDatabaseForTests();
});

describe("jobs local IndexedDB transactions", () => {
	it("serializes delayed rapid writes without reordering them", async () => {
		const database = new FakeJobsDatabase();
		database.delayNextTransaction(25);
		setJobsLocalDatabaseForTests(database.asDatabase());
		const first = workflow("job-a", "first", "2026-08-12T10:00:00.000Z");
		const second = workflow("job-a", "second", "2026-08-12T10:00:01.000Z");

		await Promise.all([
			writeStoreRecord(jobsLocalStoreNames.jobRecords, first),
			writeStoreRecord(jobsLocalStoreNames.jobRecords, second),
		]);

		const snapshot = await readIndexedJobsLocalSnapshot();
		expect(database.maxActiveTransactions).toBe(1);
		expect(database.committedTransactionIds).toEqual([1, 2, 3]);
		expect(snapshot.jobRecords).toEqual([second]);
	});

	it("captures mutation inputs at enqueue time", async () => {
		const database = new FakeJobsDatabase();
		database.delayNextTransaction(20);
		setJobsLocalDatabaseForTests(database.asDatabase());
		const record = workflow("job-a", "captured", "2026-08-12T10:00:00.000Z");

		const pending = writeStoreRecord(jobsLocalStoreNames.jobRecords, record);
		record.notes = "mutated after enqueue";
		await pending;

		expect((await readIndexedJobsLocalSnapshot()).jobRecords[0]?.notes).toBe(
			"captured",
		);
	});

	it("keeps prior durable state after an aborted workflow transaction", async () => {
		const database = new FakeJobsDatabase();
		setJobsLocalDatabaseForTests(database.asDatabase());
		const previous = workflow("job-a", "keep", "2026-08-12T10:00:00.000Z");
		const retained = {
			schemaVersion: 2 as const,
			jobId: "job-a",
			capturedAt: "2026-08-12T10:00:00.000Z",
			updatedAt: "2026-08-12T10:00:00.000Z",
			snapshotAt: null,
			rowSnapshot: null,
			detail: { id: "job-a", title: "Keep me" },
		};
		await writeJobWorkflowTransaction({ record: previous, retainedDetail: retained });
		database.failNextTransaction(new Error("Quota exceeded"));

		await expect(
			writeJobWorkflowTransaction({
				record: workflow("job-a", "erase", "2026-08-12T10:00:01.000Z"),
				retainedDetail: null,
			}),
		).rejects.toThrow("Quota exceeded");

		const snapshot = await readIndexedJobsLocalSnapshot();
		expect(snapshot.jobRecords).toEqual([previous]);
		expect(snapshot.retainedJobDetails).toMatchObject([retained]);
	});

	it("recovers the serialized queue after a failed mutation", async () => {
		const database = new FakeJobsDatabase();
		setJobsLocalDatabaseForTests(database.asDatabase());
		database.failNextTransaction(new Error("disk full"));
		const failed = workflow("job-a", "failed", "2026-08-12T10:00:00.000Z");
		const recovered = workflow("job-a", "recovered", "2026-08-12T10:00:01.000Z");

		await expect(
			writeStoreRecord(jobsLocalStoreNames.jobRecords, failed),
		).rejects.toThrow("disk full");
		await writeStoreRecord(jobsLocalStoreNames.jobRecords, recovered);

		expect((await readIndexedJobsLocalSnapshot()).jobRecords).toEqual([recovered]);
	});

	it("atomically replaces imported data while retaining only three bounded backups", async () => {
		const database = new FakeJobsDatabase();
		setJobsLocalDatabaseForTests(database.asDatabase());
		let current = snapshotFor("job-0", "2026-08-12T10:00:00.000Z");
		await importIndexedSnapshot({
			next: current,
			current: emptySnapshot(),
			mode: "replace",
			createdAt: "2026-08-12T09:59:59.000Z",
		});

		for (let index = 1; index <= 4; index += 1) {
			const next = snapshotFor(
				`job-${index}`,
				`2026-08-12T10:00:0${index}.000Z`,
			);
			await importIndexedSnapshot({
				next,
				current,
				mode: index % 2 === 0 ? "replace" : "merge",
				createdAt: `2026-08-12T10:00:0${index}.000Z`,
			});
			current = next;
		}

		const backups = await readIndexedJobsLocalBackups();
		expect(backups).toHaveLength(3);
		expect(backups.map((backup) => backup.createdAt).sort()).toEqual([
			"2026-08-12T10:00:02.000Z",
			"2026-08-12T10:00:03.000Z",
			"2026-08-12T10:00:04.000Z",
		]);
		expect(backups.every((backup) => backup.bytes > 0 && backup.bytes <= 32 * 1024 * 1024)).toBe(
			true,
		);
		expect((await readIndexedJobsLocalSnapshot()).jobRecords[0]?.jobId).toBe(
			"job-4",
		);
	});

	it("rolls back both the live import and its backup when the transaction aborts", async () => {
		const database = new FakeJobsDatabase();
		setJobsLocalDatabaseForTests(database.asDatabase());
		const current = snapshotFor("job-before", "2026-08-12T10:00:00.000Z");
		await importIndexedSnapshot({
			next: current,
			current: emptySnapshot(),
			mode: "replace",
			createdAt: "2026-08-12T10:00:00.000Z",
		});
		const backupCount = (await readIndexedJobsLocalBackups()).length;
		database.failNextTransaction(new Error("transaction aborted"));

		await expect(
			importIndexedSnapshot({
				next: snapshotFor("job-after", "2026-08-12T10:00:01.000Z"),
				current,
				mode: "replace",
				createdAt: "2026-08-12T10:00:01.000Z",
			}),
		).rejects.toThrow("transaction aborted");

		expect((await readIndexedJobsLocalSnapshot()).jobRecords[0]?.jobId).toBe(
			"job-before",
		);
		expect(await readIndexedJobsLocalBackups()).toHaveLength(backupCount);
	});

	it("clears live records and recovery backups in one transaction", async () => {
		const database = new FakeJobsDatabase();
		setJobsLocalDatabaseForTests(database.asDatabase());
		const current = snapshotFor("job-before", "2026-08-12T10:00:00.000Z");
		await importIndexedSnapshot({
			next: current,
			current: emptySnapshot(),
			mode: "replace",
			createdAt: "2026-08-12T10:00:00.000Z",
		});

		await clearIndexedJobsLocalData();

		expect((await readIndexedJobsLocalSnapshot()).jobRecords).toEqual([]);
		expect(await readIndexedJobsLocalBackups()).toEqual([]);
	});
});

function workflow(jobId: string, notes: string, now: string) {
	return updateJobWorkflowRecord(null, { notes }, { jobId, now });
}

function emptySnapshot(): JobsLocalSnapshot {
	return {
		settings: { ...DEFAULT_JOBS_LOCAL_SETTINGS },
		jobRecords: [],
		savedSearches: [],
		retainedJobDetails: [],
	};
}

function snapshotFor(jobId: string, now: string): JobsLocalSnapshot {
	return {
		...emptySnapshot(),
		jobRecords: [workflow(jobId, jobId, now)],
	};
}

type FakeRequest<T> = IDBRequest<T> & {
	result: T;
	error: DOMException | null;
};

class FakeJobsDatabase {
	readonly stores = new Map<string, Map<IDBValidKey, unknown>>();
	readonly committedTransactionIds: number[] = [];
	maxActiveTransactions = 0;
	private activeTransactions = 0;
	private nextTransactionId = 0;
	private nextDelayMs = 0;
	private nextFailure: Error | null = null;

	constructor() {
		for (const store of [
			jobsLocalStoreNames.jobRecords,
			jobsLocalStoreNames.savedSearches,
			jobsLocalStoreNames.retainedJobDetails,
			jobsLocalStoreNames.importBackups,
		]) {
			this.stores.set(store, new Map());
		}
	}

	asDatabase() {
		return {
			transaction: (
				storeNames: string | string[],
				mode: IDBTransactionMode = "readonly",
			) => this.createTransaction(storeNames, mode),
		} as unknown as IDBDatabase;
	}

	delayNextTransaction(delayMs: number) {
		this.nextDelayMs = delayMs;
	}

	failNextTransaction(error: Error) {
		this.nextFailure = error;
	}

	private createTransaction(
		storeNames: string | string[],
		mode: IDBTransactionMode,
	) {
		this.activeTransactions += 1;
		this.maxActiveTransactions = Math.max(
			this.maxActiveTransactions,
			this.activeTransactions,
		);
		const id = (this.nextTransactionId += 1);
		const delayMs = this.nextDelayMs;
		const failure = this.nextFailure;
		this.nextDelayMs = 0;
		this.nextFailure = null;
		return new FakeTransaction({
			database: this,
			id,
			storeNames: typeof storeNames === "string" ? [storeNames] : storeNames,
			mode,
			delayMs,
			failure,
		}) as unknown as IDBTransaction;
	}

	transactionFinished(id: number, committed: boolean) {
		this.activeTransactions -= 1;
		if (committed) {
			this.committedTransactionIds.push(id);
		}
	}
}

class FakeTransaction {
	onabort: ((this: IDBTransaction, ev: Event) => unknown) | null = null;
	oncomplete: ((this: IDBTransaction, ev: Event) => unknown) | null = null;
	onerror: ((this: IDBTransaction, ev: Event) => unknown) | null = null;
	error: DOMException | null = null;
	private pending = 0;
	private aborted = false;
	private finishing = false;
	private readonly working = new Map<string, Map<IDBValidKey, unknown>>();

	constructor(
		private readonly options: {
			database: FakeJobsDatabase;
			id: number;
			storeNames: string[];
			mode: IDBTransactionMode;
			delayMs: number;
			failure: Error | null;
		},
	) {
		for (const storeName of options.storeNames) {
			this.working.set(
				storeName,
				new Map(options.database.stores.get(storeName) ?? []),
			);
		}
		queueMicrotask(() => this.maybeFinish());
	}

	objectStore(storeName: string) {
		if (!this.working.has(storeName)) {
			throw new Error(`Store ${storeName} is outside this transaction.`);
		}
		const keyPath =
			storeName === jobsLocalStoreNames.savedSearches ||
			storeName === jobsLocalStoreNames.importBackups
				? "id"
				: "jobId";
		return {
			put: (value: unknown) =>
				this.request(() => {
					const record = value as Record<string, unknown>;
					const key = record[keyPath];
					if (typeof key !== "string") {
						throw new Error(`Missing ${keyPath}.`);
					}
					this.working.get(storeName)?.set(key, structuredClone(value));
					return key;
				}),
			delete: (key: IDBValidKey) =>
				this.request(() => this.working.get(storeName)?.delete(key)),
			clear: () =>
				this.request(() => {
					this.working.get(storeName)?.clear();
					return undefined;
				}),
			getAll: () =>
				this.request(() =>
					Array.from(this.working.get(storeName)?.values() ?? []).map((value) =>
						structuredClone(value),
					),
				),
		};
	}

	abort() {
		this.abortWith(this.error ?? new DOMException("Transaction aborted", "AbortError"));
	}

	private request<T>(operation: () => T) {
		this.pending += 1;
		const request = {
			result: undefined as T,
			error: null,
			onsuccess: null,
			onerror: null,
		} as unknown as FakeRequest<T>;
		queueMicrotask(() => {
			if (this.aborted) {
				return;
			}
			if (this.options.failure) {
				this.abortWith(this.options.failure);
				return;
			}
			try {
				request.result = operation();
				request.onsuccess?.call(request, new Event("success"));
			} catch (caught) {
				this.abortWith(
					caught instanceof Error ? caught : new Error("Fake request failed."),
				);
				return;
			}
			this.pending -= 1;
			this.maybeFinish();
		});
		return request;
	}

	private maybeFinish() {
		if (this.aborted || this.finishing || this.pending > 0) {
			return;
		}
		this.finishing = true;
		setTimeout(() => {
			if (this.aborted) {
				return;
			}
			if (this.options.mode === "readwrite") {
				for (const [storeName, records] of this.working) {
					this.options.database.stores.set(storeName, new Map(records));
				}
			}
			this.options.database.transactionFinished(this.options.id, true);
			this.oncomplete?.call(this as unknown as IDBTransaction, new Event("complete"));
		}, this.options.delayMs);
	}

	private abortWith(error: Error | DOMException) {
		if (this.aborted) {
			return;
		}
		this.aborted = true;
		this.error =
			error instanceof DOMException
				? error
				: new DOMException(error.message, "UnknownError");
		this.options.database.transactionFinished(this.options.id, false);
		this.onerror?.call(this as unknown as IDBTransaction, new Event("error"));
		this.onabort?.call(this as unknown as IDBTransaction, new Event("abort"));
	}
}
