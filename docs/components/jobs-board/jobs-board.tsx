"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
	filterAndSortJobs,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { useJobBoardFilterState } from "@/components/jobs-board/jobs-board-filter-state";
import { JobsBoardEmpty } from "@/components/jobs-board/jobs-board-empty";
import { JobsBoardList } from "@/components/jobs-board/jobs-board-list";
import { JobsBoardMetrics } from "@/components/jobs-board/jobs-board-metrics";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { JobsBoardPreviewSheet } from "@/components/jobs-board/jobs-board-preview-sheet";
import { JobsBoardToolbar } from "@/components/jobs-board/jobs-board-toolbar";
import {
	loadEntityChunk,
	loadInitialJobsChunk,
	loadSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	JobDetail,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import { detailPath, J, text } from "@/components/openopps-search/search-utils";

type JobsBoardProps = {
	initialJobId?: string;
};

function errorMessage(error: unknown) {
	if (error instanceof Error) {
		return error.message;
	}
	return "Unexpected error loading jobs board data.";
}

function findRowById(rows: SearchRow[], jobId: string) {
	return rows.find((row) => text(row[J.id]) === jobId) ?? null;
}

export function JobsBoard({ initialJobId }: JobsBoardProps) {
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [rows, setRows] = useState<SearchRow[]>([]);
	const [fullRowsLoaded, setFullRowsLoaded] = useState(false);
	const [loading, setLoading] = useState(true);
	const [loadingFullIndex, setLoadingFullIndex] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [detail, setDetail] = useState<JobDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState<string | null>(null);

	const {
		filters,
		deferredFilters,
		selectedJobId,
		setFilters,
		setSelectedJobId,
		clearFilters,
		activeFilterCount,
	} = useJobBoardFilterState();

	useEffect(() => {
		if (initialJobId && !selectedJobId) {
			void setSelectedJobId(initialJobId);
		}
	}, [initialJobId, selectedJobId, setSelectedJobId]);

	useEffect(() => {
		let mounted = true;

		async function load() {
			try {
				const nextManifest = await loadSearchManifest();
				const initialChunk = await loadInitialJobsChunk(nextManifest);
				if (mounted) {
					setManifest(nextManifest);
					setRows(initialChunk.rows);
					setFullRowsLoaded(
						initialChunk.count >= nextManifest.entities.jobs.count,
					);
					setError(null);
				}
			} catch (caught) {
				if (mounted) {
					setError(errorMessage(caught));
				}
			} finally {
				if (mounted) {
					setLoading(false);
				}
			}
		}

		void load();
		return () => {
			mounted = false;
		};
	}, []);

	const needsFullIndex = activeFilterCount > 0 || Boolean(selectedJobId);

	useEffect(() => {
		if (!manifest || !needsFullIndex || fullRowsLoaded || loadingFullIndex) {
			return;
		}
		const currentManifest = manifest;
		let mounted = true;

		async function loadFullIndex() {
			setLoadingFullIndex(true);
			try {
				const fullChunk = await loadEntityChunk(currentManifest, "jobs");
				if (mounted) {
					setRows(fullChunk.rows);
					setFullRowsLoaded(true);
					setError(null);
				}
			} catch (caught) {
				if (mounted) {
					setError(errorMessage(caught));
				}
			} finally {
				if (mounted) {
					setLoadingFullIndex(false);
				}
			}
		}

		void loadFullIndex();
		return () => {
			mounted = false;
		};
	}, [fullRowsLoaded, loadingFullIndex, manifest, needsFullIndex]);

	const sortKey: JobSortKey = deferredFilters.query ? "relevance" : "latest";

	const visibleRows = useMemo(() => {
		if (rows.length === 0) {
			return [];
		}
		return filterAndSortJobs(rows, deferredFilters, sortKey);
	}, [deferredFilters, rows, sortKey]);

	const selectedRow = useMemo(
		() => (selectedJobId ? findRowById(visibleRows, selectedJobId) : null),
		[selectedJobId, visibleRows],
	);

	const detailRoot =
		manifest?.detailShards?.root ?? "/data/openopps-search/jobs-details";

	useEffect(() => {
		if (!selectedJobId) {
			return;
		}

		const jobId = selectedJobId;
		let mounted = true;
		const controller = new AbortController();

		async function loadDetail() {
			setDetailLoading(true);
			setDetailError(null);
			try {
				const path = detailPath(detailRoot, jobId);
				const response = await fetch(path, {
					signal: controller.signal,
					cache: "force-cache",
				});
				if (!response.ok) {
					throw new Error(`Detail bucket not found (${response.status})`);
				}
				const payload = (await response.json()) as Record<string, JobDetail>;
				const nextDetail = payload[jobId];
				if (!nextDetail) {
					throw new Error("Detail record not found in bucket.");
				}
				if (mounted) {
					setDetail(nextDetail);
				}
			} catch (caught) {
				if (!mounted || controller.signal.aborted) {
					return;
				}
				setDetail(null);
				setDetailError(errorMessage(caught));
			} finally {
				if (mounted) {
					setDetailLoading(false);
				}
			}
		}

		void loadDetail();
		return () => {
			mounted = false;
			controller.abort();
		};
	}, [detailRoot, selectedJobId]);

	const handleSelectJob = (jobId: string) => {
		void setSelectedJobId(jobId);
	};

	const handleClosePreview = () => {
		void setSelectedJobId(null);
	};

	const activeDetail =
		selectedJobId && detail?.id === selectedJobId ? detail : null;
	const activeDetailLoading = Boolean(selectedJobId && detailLoading);
	const activeDetailError = selectedJobId ? detailError : null;

	const indexNote =
		needsFullIndex && loadingFullIndex
			? "Loading the full static jobs index for global matches."
			: !fullRowsLoaded
				? "Showing the latest open jobs. Search or filter to load the full index."
				: null;

	return (
		<section className="not-prose mx-auto w-full max-w-7xl px-5 py-8 sm:px-8 lg:px-10">
			<div className="opps-ledger-shell">
				<JobsBoardMetrics manifest={manifest} matchCount={visibleRows.length} />

				<div className="mt-4">
					<JobsBoardToolbar
						filters={filters}
						manifest={manifest}
						matchCount={visibleRows.length}
						activeFilterCount={activeFilterCount}
						onChange={setFilters}
						onClear={clearFilters}
					/>
				</div>

				{indexNote ? (
					<p className="mt-3 text-xs text-muted-foreground">{indexNote}</p>
				) : null}

				{error ? (
					<div className="mt-4 rounded-2xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
						{error}
					</div>
				) : null}

				{loading ? (
					<div className="opps-empty mt-4 min-h-[24rem] text-sm text-muted-foreground">
						<Loader2 className="mr-2 size-4 animate-spin" />
						Loading open jobs index…
					</div>
				) : null}

				{!loading && !error ? (
					<div className="mt-4">
						{visibleRows.length === 0 ? (
							<JobsBoardEmpty
								matchCount={visibleRows.length}
								activeFilterCount={activeFilterCount}
								onClearFilters={clearFilters}
							/>
						) : (
							<div className="grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
								<JobsBoardList
									rows={visibleRows}
									selectedJobId={selectedJobId ?? ""}
									onSelectJob={handleSelectJob}
								/>
								<div className="hidden lg:block">
									<JobsBoardPreview
										row={selectedRow}
										detail={activeDetail}
										loading={activeDetailLoading}
										error={activeDetailError}
										onClose={selectedRow ? handleClosePreview : undefined}
									/>
								</div>
							</div>
						)}
					</div>
				) : null}
			</div>

			<JobsBoardPreviewSheet
				open={Boolean(selectedRow)}
				row={selectedRow}
				detail={activeDetail}
				loading={activeDetailLoading}
				error={activeDetailError}
				onClose={handleClosePreview}
			/>
		</section>
	);
}
