"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
	invalidateBrowserSearchSnapshotRuntime,
	loadJobsOfflineReleasePlan,
} from "@/components/openopps-search/search-index-loader";
import {
	disableJobsOfflineCache,
	isJobsOfflineOptedIn,
	JobsOfflineCacheError,
	prepareJobsOfflineCache,
	readJobsOfflineReady,
	setJobsOfflineOptIn,
	verifyOrDiscardJobsOfflineCache,
	type JobsOfflineCacheProgress,
	type JobsOfflineCacheReady,
} from "@/lib/jobs-offline-cache";
import { resetJobsSearchWorkerRuntime } from "@/lib/jobs-search-worker-client";

export type JobsOfflineCacheStatus =
	| "checking"
	| "downloading"
	| "error"
	| "off"
	| "ready"
	| "stale"
	| "unsupported";

export type JobsOfflineCacheView = {
	optedIn: boolean;
	status: JobsOfflineCacheStatus;
	error: string | null;
	progress: JobsOfflineCacheProgress | null;
	ready: JobsOfflineCacheReady | null;
	enable: () => Promise<void>;
	disable: () => Promise<void>;
	retry: () => Promise<void>;
};

export function useJobsOfflineCache(active: boolean): JobsOfflineCacheView {
	const [optedIn, setOptedIn] = useState(() => isJobsOfflineOptedIn());
	const [status, setStatus] = useState<JobsOfflineCacheStatus>(
		optedIn ? "checking" : "off",
	);
	const [error, setError] = useState<string | null>(null);
	const [progress, setProgress] = useState<JobsOfflineCacheProgress | null>(null);
	const [ready, setReady] = useState<JobsOfflineCacheReady | null>(() =>
		optedIn ? readJobsOfflineReady() : null,
	);
	const operation = useRef<AbortController | null>(null);

	const inspect = useCallback(async () => {
		if (!isJobsOfflineOptedIn()) {
			setOptedIn(false);
			setStatus("off");
			setReady(null);
			setError(null);
			return;
		}
		const stored = readJobsOfflineReady();
		if (!stored) {
			setOptedIn(true);
			setStatus("stale");
			setReady(null);
			return;
		}
		const controller = new AbortController();
		operation.current?.abort();
		operation.current = controller;
		setStatus("checking");
		setError(null);
		try {
			const plan = await loadJobsOfflineReleasePlan(controller.signal);
			if (!plan || plan.releaseId !== stored.releaseId) {
				setReady(stored);
				setStatus("stale");
				return;
			}
			await verifyOrDiscardJobsOfflineCache(plan, stored, {
				signal: controller.signal,
			});
			setReady(stored);
			setStatus("ready");
		} catch (caught) {
			if (controller.signal.aborted) return;
			const remainingReady = readJobsOfflineReady();
			if (!remainingReady) {
				rebindJobsSearchRuntime();
			}
			setReady(remainingReady);
			setStatus(cacheStatusForError(caught));
			setError(offlineErrorMessage(caught));
		} finally {
			if (operation.current === controller) operation.current = null;
		}
	}, []);

	useEffect(() => {
		if (!active) return;
		const timeout = window.setTimeout(() => void inspect(), 0);
		return () => {
			window.clearTimeout(timeout);
			operation.current?.abort();
		};
	}, [active, inspect]);

	const enable = useCallback(async () => {
		const controller = new AbortController();
		operation.current?.abort();
		operation.current = controller;
		setJobsOfflineOptIn(true);
		setOptedIn(true);
		setStatus("downloading");
		setError(null);
		setProgress(null);
		try {
			const plan = await loadJobsOfflineReleasePlan(controller.signal);
			if (!plan) {
				throw new JobsOfflineCacheError(
					"unsupported",
					"Verified offline search requires an immutable v7 public-data release.",
				);
			}
			const receipt = await prepareJobsOfflineCache(plan, {
				signal: controller.signal,
				onProgress: setProgress,
			});
			rebindJobsSearchRuntime();
			setReady(receipt);
			setStatus("ready");
			setProgress(null);
		} catch (caught) {
			if (controller.signal.aborted) return;
			setReady(readJobsOfflineReady());
			setStatus(cacheStatusForError(caught));
			setError(offlineErrorMessage(caught));
			setProgress(null);
		} finally {
			if (operation.current === controller) operation.current = null;
		}
	}, []);

	const disable = useCallback(async () => {
		operation.current?.abort();
		operation.current = null;
		setStatus("checking");
		setError(null);
		try {
			rebindJobsSearchRuntime();
			await disableJobsOfflineCache();
			setOptedIn(false);
			setReady(null);
			setProgress(null);
			setStatus("off");
		} catch (caught) {
			setStatus(cacheStatusForError(caught));
			setError(offlineErrorMessage(caught));
		}
	}, []);

	return {
		optedIn,
		status,
		error,
		progress,
		ready,
		enable,
		disable,
		retry: enable,
	};
}

function rebindJobsSearchRuntime() {
	resetJobsSearchWorkerRuntime();
	invalidateBrowserSearchSnapshotRuntime();
}

function cacheStatusForError(caught: unknown): JobsOfflineCacheStatus {
	return caught instanceof JobsOfflineCacheError && caught.code === "unsupported"
		? "unsupported"
		: "error";
}

function offlineErrorMessage(caught: unknown) {
	return caught instanceof Error
		? caught.message
		: "Verified offline search could not be prepared. Try again while online.";
}
