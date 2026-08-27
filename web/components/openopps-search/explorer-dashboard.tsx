"use client";

import {
	Activity,
	Archive,
	BarChart3,
	Database,
	FileSearch,
	Globe2,
	LineChart,
	MapPin,
	Network,
	Route,
	Sparkles,
	TableProperties,
	Tags,
} from "lucide-react";
import Link from "next/link";
import {
	startTransition,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type ComponentType,
	type ReactNode,
	type SVGProps,
} from "react";
import { useQueryStates } from "nuqs";

import type {
	Entity,
	LineageAggregate,
	SearchDashboard,
	SearchManifest,
	SearchRow,
	SearchSuggestion,
	SearchTopValue,
} from "@/components/openopps-search/search-types";
import {
	formatCount,
	formatDate,
	J,
	rankSuggestions,
	text,
} from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
	DEFAULT_EXPLORER_FILTERS,
	DEFAULT_EXPLORER_SORT,
	type ExplorerFilters,
} from "./explorer-filter-engine";
import { explorerQueryParsers } from "./explorer-filter-state";
import {
	buildLineageNetworkModel,
	type LineageNetworkModel,
	type LineagePairRow,
	type LineagePathRow,
} from "./explorer-lineage-model";
import { loadInitialJobsChunk } from "./search-index-loader";
import {
	coverageShare,
	explorerDeferredStyle,
	ExplorerEmptyPanel,
	ExplorerMetric,
	jobsBoardSearchHref,
	RankedLedgerList,
	RankedLedgerSkeleton,
	rankedLedgerReservePx,
	rankedTopValueItems,
	CoverageMeter,
	type RankedLedgerItem,
} from "./explorer-shared";

const COVERAGE_LEDGER_LIMIT = 8;
const BOARD_LEDGER_LIMIT = 6;
const LATEST_JOB_TEASER_LIMIT = 8;
const LINEAGE_RESERVE_PX = 720;
const SUGGESTION_RESERVE_PX = 280;
const INDEX_RESERVE_PX = 360;

type ExplorerDashboardProps = {
	manifest: SearchManifest | null;
	lineage: LineageAggregate | null;
	loading: boolean;
	warning?: string | null;
	onInspectRows: () => void;
	onRetry?: () => void;
	onInspectFacet?: (next: ExplorerInspectFacet) => void;
};

export type ExplorerInspectFacet = {
	entity: Entity;
	filters: Partial<ExplorerFilters>;
};

type DashboardModel = SearchDashboard & {
	fromGeneratedDashboard: boolean;
};

export function ExplorerDashboard({
	manifest,
	lineage,
	loading,
	warning,
	onInspectRows,
	onRetry,
	onInspectFacet,
}: ExplorerDashboardProps) {
	const dashboard = useMemo(() => buildDashboardModel(manifest), [manifest]);
	const suggestionCount = useMemo(() => countSuggestions(manifest), [manifest]);
	const inspect = useExplorerInspect(onInspectRows, onInspectFacet);
	const coverageLabels = useMemo(
		() => ({
			sources: labelMap(manifest?.suggestions?.sources),
			providers: labelMap(manifest?.suggestions?.providers),
			locations: labelMap(manifest?.suggestions?.locations),
			departments: labelMap(manifest?.suggestions?.departments),
			companies: labelMap(manifest?.suggestions?.companies),
			skills: labelMap(manifest?.suggestions?.skills),
		}),
		[manifest],
	);
	const openShare = coverageShare(dashboard?.totals.openJobs, dashboard?.totals.jobs);
	const artifactShare = coverageShare(
		dashboard?.artifacts.detailShardRecords,
		dashboard?.totals.jobs ?? manifest?.entities.jobs.count,
	);
	const coverageReserve = loading ? COVERAGE_LEDGER_LIMIT : 0;
	const boardReserve = loading ? BOARD_LEDGER_LIMIT : 0;

	return (
		<div className="min-w-0 space-y-4 [&>*]:min-w-0">
			<div className="flex min-w-0 flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
				<div className="min-w-0">
					<p className="opps-kicker">OpenOppsDB explorer</p>
					<h1 className="mt-2 font-heading text-2xl font-semibold leading-tight tracking-normal md:text-3xl">
						Data pipeline dashboard
					</h1>
					<p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
						Snapshot coverage, route readiness, distribution, and quality
						metadata for the static OpenOppsDB search index.
					</p>
				</div>
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={onInspectRows}
					disabled={!manifest}
				>
					<FileSearch className="mr-2 size-4" width={16} height={16} aria-hidden="true" />
					Inspect rows
				</Button>
			</div>

			{warning ? (
				<div className="flex min-w-0 flex-col gap-2 rounded-[var(--opps-radius-lg)] border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning-foreground sm:flex-row sm:items-center sm:justify-between">
					<span>{warning}</span>
					{onRetry ? (
						<Button type="button" variant="outline" size="sm" onClick={onRetry}>
							Retry index
						</Button>
					) : null}
				</div>
			) : null}

			<p className="opps-kicker">Snapshot</p>
			<div className="grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-5 [&>*]:min-w-0">
				<ExplorerMetric
					label="sources"
					value={dashboard?.totals.sourceRows}
					onActivate={() => inspect("jobs")}
				/>
				<ExplorerMetric
					label="providers"
					value={dashboard?.totals.providerRoutes}
					onActivate={() => inspect("providers")}
				/>
				<ExplorerMetric
					label="boards"
					value={dashboard?.totals.boards}
					onActivate={() => inspect("boards")}
				/>
				<ExplorerMetric
					label="jobs"
					value={dashboard?.totals.jobs}
					sharePercent={openShare}
					shareLabel={`${openShare}% open`}
					onActivate={() => inspect("jobs")}
				/>
				<ExplorerMetric
					label="open jobs"
					value={dashboard?.totals.openJobs}
					sharePercent={openShare}
					shareLabel={`${openShare}% open`}
					onActivate={() => inspect("jobs", { jobStatus: "open" })}
				/>
			</div>

			<LatestJobsTeaser
				manifest={manifest}
				pending={loading}
				sync={dashboard?.sync}
			/>

			<p className="opps-kicker">Coverage</p>
			<div className="grid min-w-0 gap-3 xl:grid-cols-3 [&>*]:min-w-0">
				<DashboardCard
					title="Source coverage"
					icon={Globe2}
					description="Sources ranked by generated job coverage. Click a row to inspect jobs for that source."
				>
					<RankedLedgerList
						emptyLabel="Source coverage awaits the manifest v4 dashboard aggregate."
						reserveCount={coverageReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.sourcesByJobs, {
							labels: coverageLabels.sources,
							limit: COVERAGE_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							onSelect: (value) => inspect("jobs", { source: value }),
							inspectNoun: "jobs",
						})}
					/>
				</DashboardCard>
				<DashboardCard
					title="Provider coverage"
					icon={Network}
					description="Providers ranked by generated job coverage. Click a row to inspect jobs for that provider."
				>
					<RankedLedgerList
						emptyLabel="Provider coverage awaits the manifest v4 dashboard aggregate."
						reserveCount={coverageReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.providersByJobs, {
							labels: coverageLabels.providers,
							limit: COVERAGE_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							onSelect: (value) => inspect("jobs", { provider: value }),
							inspectNoun: "jobs",
						})}
					/>
				</DashboardCard>
				<DashboardCard
					title="Locations"
					icon={MapPin}
					description="Top locations in this snapshot. Click a row to inspect matching jobs."
				>
					<RankedLedgerList
						emptyLabel="Location suggestions are not in this artifact yet."
						reserveCount={coverageReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.locations, {
							labels: coverageLabels.locations,
							limit: COVERAGE_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							onSelect: (value) => inspect("jobs", { location: value }),
							inspectNoun: "jobs",
						})}
					/>
				</DashboardCard>
			</div>

			<div
				className="grid min-w-0 gap-3 xl:grid-cols-3 [&>*]:min-w-0"
				style={explorerDeferredStyle(rankedLedgerReservePx(BOARD_LEDGER_LIMIT) + 120)}
			>
				<DashboardCard
					title="Departments"
					icon={TableProperties}
					description="Explorer inspect has no department facet; rows open the jobs board."
				>
					<RankedLedgerList
						emptyLabel="Department suggestions are not in this artifact yet."
						reserveCount={boardReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.departments, {
							labels: coverageLabels.departments,
							limit: BOARD_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							hrefFor: (value) => jobsBoardSearchHref({ department: value }),
						})}
					/>
				</DashboardCard>
				<DashboardCard
					title="Companies"
					icon={LineChart}
					description="Explorer inspect has no company facet; rows search the jobs board."
				>
					<RankedLedgerList
						emptyLabel="Company suggestions are not in this artifact yet."
						reserveCount={boardReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.companies, {
							labels: coverageLabels.companies,
							limit: BOARD_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							hrefFor: (value) => jobsBoardSearchHref({ q: value }),
						})}
					/>
				</DashboardCard>
				<DashboardCard
					title="Skills"
					icon={Tags}
					description="Explorer inspect has no skill facet; rows open the jobs board."
				>
					<RankedLedgerList
						emptyLabel="Skill suggestions are not in this artifact yet."
						reserveCount={boardReserve}
						busy={loading}
						items={rankedTopValueItems(dashboard?.top.skills, {
							labels: coverageLabels.skills,
							limit: BOARD_LEDGER_LIMIT,
							snapshotTotal: dashboard?.totals.jobs,
							hrefFor: (value) => jobsBoardSearchHref({ skill: value }),
						})}
					/>
				</DashboardCard>
			</div>

			<div
				className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)] [&>*]:min-w-0"
				style={explorerDeferredStyle(rankedLedgerReservePx(COVERAGE_LEDGER_LIMIT) + 160)}
			>
				<DashboardCard
					title="Data quality"
					icon={Sparkles}
					description="Completeness checks emitted by the search-index generator. Bars are true 0–100% coverage."
				>
					<QualityList metrics={dashboard?.dataQuality} reserveCount={coverageReserve} busy={loading} />
				</DashboardCard>
				<DashboardCard
					title="Route health"
					icon={Route}
					description="Support and route-status distribution. Color is paired with a text badge and label."
				>
					<div className="min-w-0 space-y-4">
						<div className="min-w-0">
							<h3 className="mb-2 font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
								Support
							</h3>
							<RankedLedgerList
								emptyLabel="Support-level counts are not in this artifact yet."
								reserveCount={boardReserve}
								busy={loading}
								items={routeHealthItems(
									dashboard?.routeHealth.supportLevels,
									dashboard?.totals.providerRoutes,
									(value) => inspect("providers", { support: value }),
								)}
							/>
						</div>
						<div className="min-w-0 border-t border-border/70 pt-3">
							<h3 className="mb-2 font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
								Route status
							</h3>
							<RankedLedgerList
								emptyLabel="Route-status counts are not in this artifact yet."
								reserveCount={boardReserve}
								busy={loading}
								items={routeHealthItems(
									dashboard?.routeHealth.routeStatuses,
									dashboard?.totals.providerRoutes,
									(value) => inspect("providers", { routeStatus: value }),
								)}
							/>
						</div>
					</div>
				</DashboardCard>
			</div>

			<p className="opps-kicker">Lineage</p>
			<LineageSection
				lineage={lineage}
				loading={loading}
				onInspectRows={onInspectRows}
				inspect={inspect}
			/>

			<section className="min-w-0" style={explorerDeferredStyle(SUGGESTION_RESERVE_PX)}>
				<div className="mb-3 flex min-w-0 items-start gap-2">
					<div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--opps-radius-md)] border border-primary/25 bg-primary/10 text-primary">
						<BarChart3 className="size-4" width={16} height={16} aria-hidden="true" />
					</div>
					<div className="min-w-0">
						<h2 className="font-heading text-base font-semibold leading-snug tracking-normal">
							Suggestion index
						</h2>
						<p className="mt-1 text-xs leading-5 text-muted-foreground">
							Generated fuzzy-match surfaces. Count plus top value; inspect when
							the facet exists, otherwise open the jobs board.
						</p>
					</div>
				</div>
				<div className="grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0">
					<SuggestionStat
						label="sources"
						values={manifest?.suggestions?.sources}
						onActivate={(value) => inspect("jobs", { source: value })}
					/>
					<SuggestionStat
						label="providers"
						values={manifest?.suggestions?.providers}
						onActivate={(value) => inspect("jobs", { provider: value })}
					/>
					<SuggestionStat
						label="locations"
						values={manifest?.suggestions?.locations}
						onActivate={(value) => inspect("jobs", { location: value })}
					/>
					<SuggestionStat
						label="departments"
						values={manifest?.suggestions?.departments}
						hrefFor={(value) => jobsBoardSearchHref({ department: value })}
					/>
					<SuggestionStat
						label="companies"
						values={manifest?.suggestions?.companies}
						hrefFor={(value) => jobsBoardSearchHref({ q: value })}
					/>
					<SuggestionStat
						label="skills"
						values={manifest?.suggestions?.skills}
						hrefFor={(value) => jobsBoardSearchHref({ skill: value })}
					/>
					<SuggestionStat
						label="workplaces"
						values={manifest?.suggestions?.workplaces}
						onActivate={(value) => inspect("jobs", { workplace: value })}
					/>
					<SuggestionStat
						label="employment"
						values={manifest?.suggestions?.employmentTypes}
						onActivate={(value) => inspect("jobs", { employment: value })}
					/>
				</div>
			</section>

			<p className="opps-kicker">Index</p>
			<div
				className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] [&>*]:min-w-0"
				style={explorerDeferredStyle(INDEX_RESERVE_PX)}
			>
				<DashboardCard
					title="Snapshot provenance"
					icon={Database}
					description="Where the dashboard data came from and how complete this artifact is."
				>
					<MetadataGrid
						items={[
							{
								label: "Snapshot",
								value: dashboard?.snapshotAt
									? formatDate(dashboard.snapshotAt)
									: loading
										? "Loading"
										: "Not declared",
							},
							{
								label: "Database",
								value: manifest?.source.database ?? "kaggle/openoppsdb.sqlite",
							},
							{
								label: "Tables",
								value: manifest?.source.tables?.length
									? manifest.source.tables.join(", ")
									: "Not declared",
							},
							{
								label: "Counts",
								value: manifest?.counts?.snapshot
									? "Snapshot counts"
									: manifest?.counts?.catalog
										? "Catalog counts"
										: "Entity counts",
							},
							{
								label: "Dashboard",
								value: dashboard?.fromGeneratedDashboard
									? "Generated aggregate"
									: "Manifest fallback",
							},
							{ label: "Suggestions", value: formatCount(suggestionCount) },
						]}
					/>
				</DashboardCard>

				<DashboardCard
					title="Schema and artifacts"
					icon={Archive}
					description="Static index version, chunking, detail shards, and row stores."
				>
					<MetadataGrid
						items={[
							{ label: "Manifest", value: `v${manifest?.version ?? "?"}` },
							{
								label: "Job chunks",
								value: formatCount(dashboard?.artifacts.jobChunks),
							},
							{
								label: "Detail buckets",
								value: formatCount(dashboard?.artifacts.detailShardBuckets),
							},
							{
								label: "Detail records",
								value: formatCount(dashboard?.artifacts.detailShardRecords),
							},
							{
								label: "Jobs rows",
								value: formatCount(manifest?.entities.jobs.count),
							},
							{
								label: "Board rows",
								value: formatCount(manifest?.entities.boards.count),
							},
						]}
					/>
					<CoverageMeter
						percent={artifactShare}
						tone="info"
						label={`${artifactShare}% shards`}
					/>
				</DashboardCard>
			</div>

			<div className="flex justify-end border-t border-border/70 pt-3">
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={onInspectRows}
					disabled={!manifest}
				>
					<FileSearch className="mr-2 size-4" width={16} height={16} aria-hidden="true" />
					Inspect rows
				</Button>
			</div>
		</div>
	);
}

function useExplorerInspect(
	onInspectRows: () => void,
	onInspectFacet?: (next: ExplorerInspectFacet) => void,
) {
	const [, setQuery] = useQueryStates(explorerQueryParsers, {
		history: "replace",
		shallow: true,
		clearOnDefault: true,
	});

	return useCallback(
		(entity: Entity, patch: Partial<ExplorerFilters> = {}) => {
			onInspectFacet?.({ entity, filters: patch });
			const nextFilters = { ...DEFAULT_EXPLORER_FILTERS, ...patch };
			void setQuery({
				entity,
				sort: DEFAULT_EXPLORER_SORT[entity],
				page: 1,
				q: nextFilters.query,
				source: nextFilters.source,
				provider: nextFilters.provider,
				jobStatus: nextFilters.jobStatus,
				support: nextFilters.support,
				routeStatus: nextFilters.routeStatus,
				workplace: nextFilters.workplace,
				employment: nextFilters.employment,
				location: nextFilters.location,
			});
			onInspectRows();
		},
		[onInspectFacet, onInspectRows, setQuery],
	);
}

function useLatestOpenJobs(manifest: SearchManifest | null) {
	const path = manifest?.entities.jobs.initialPath ?? "";
	const [result, setResult] = useState<{ path: string; rows: SearchRow[] } | null>(
		null,
	);

	useEffect(() => {
		if (!path || !manifest) {
			return;
		}
		const requestedPath = path;
		let cancelled = false;
		void loadInitialJobsChunk(manifest)
			.then((chunk) => {
				if (cancelled) {
					return;
				}
				setResult({
					path: requestedPath,
					rows: takeLatestOpenJobs(chunk.rows, LATEST_JOB_TEASER_LIMIT),
				});
			})
			.catch(() => {
				if (!cancelled) {
					setResult({ path: requestedPath, rows: [] });
				}
			});
		return () => {
			cancelled = true;
		};
	}, [manifest, path]);

	if (!path) {
		return { rows: [] as SearchRow[], loading: false };
	}
	const resolved = result?.path === path ? result.rows : [];
	return { rows: resolved, loading: result?.path !== path };
}

function takeLatestOpenJobs(rows: SearchRow[], limit: number) {
	const taken: SearchRow[] = [];
	for (const row of rows) {
		const status = text(row[J.status]).toLowerCase();
		if (status && status !== "open") {
			continue;
		}
		taken.push(row);
		if (taken.length >= limit) {
			break;
		}
	}
	return taken;
}

function LatestJobsTeaser({
	manifest,
	pending,
	sync,
}: {
	manifest: SearchManifest | null;
	pending: boolean;
	sync: SearchDashboard["sync"] | undefined;
}) {
	const { rows, loading } = useLatestOpenJobs(manifest);
	const waiting = pending || loading;
	const reserveCount = waiting || rows.length > 0 ? LATEST_JOB_TEASER_LIMIT : 0;
	return (
		<DashboardCard
			title="Latest open jobs"
			icon={Activity}
			description="Fresh titles from the latest-jobs chunk. Open a row on the jobs board."
		>
			<div className="mb-3 min-h-4 font-mono text-[0.72rem] tracking-normal text-muted-foreground">
				{sync?.totals7d ? (
					<p>
						<span className="text-accent">7d sync</span>
						{" · "}
						{formatCount(sync.totals7d.new)} new
						{" · "}
						{formatCount(sync.totals7d.changed)} changed
						{" · "}
						{formatCount(sync.totals7d.closed)} closed
						{" · "}
						{formatCount(sync.totals7d.reopened)} reopened
					</p>
				) : waiting ? (
					<p aria-hidden="true">&nbsp;</p>
				) : null}
			</div>
			{waiting ? (
				<>
					<p className="sr-only">Loading latest open jobs…</p>
					<RankedLedgerSkeleton count={reserveCount} />
				</>
			) : rows.length === 0 ? (
				<p className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 px-3 py-3 text-sm text-muted-foreground">
					Latest open jobs are not in this snapshot yet.
				</p>
			) : (
				<ul
					className="min-w-0 space-y-2"
					style={{ minHeight: rankedLedgerReservePx(Math.max(rows.length, reserveCount)) }}
				>
					{rows.map((row) => {
						const id = text(row[J.id]);
						const title = text(row[J.title]) || "Untitled role";
						const company = text(row[J.company]) || text(row[J.board]);
						const source = text(row[J.source]) || "source";
						return (
							<li key={id || title} className="min-w-0">
								<Link
									href={jobsBoardSearchHref({ job: id })}
									className="opps-provider-row min-w-0 w-full hover:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
								>
									<div className="min-w-0">
										<div className="truncate text-sm font-semibold">{title}</div>
										<div className="mt-0.5 truncate font-mono text-[0.68rem] tracking-normal text-muted-foreground">
											{company} · {source}
										</div>
									</div>
									<span className="shrink-0 font-mono text-[0.68rem] tabular-nums tracking-normal text-muted-foreground">
										{formatDate(text(row[J.latestObserved]))}
									</span>
								</Link>
							</li>
						);
					})}
				</ul>
			)}
			<div className="mt-3 flex justify-end">
				<Button asChild variant="outline" size="sm">
					<Link href="/">Open jobs board</Link>
				</Button>
			</div>
		</DashboardCard>
	);
}

function buildDashboardModel(manifest: SearchManifest | null): DashboardModel | null {
	if (!manifest) {
		return null;
	}
	if (manifest.dashboard) {
		return { ...manifest.dashboard, fromGeneratedDashboard: true };
	}
	const snapshot = manifest.counts?.snapshot;
	return {
		snapshotAt: manifest.snapshotAt,
		totals: {
			sourceRows: snapshot?.sourceRows ?? manifest.facets.sources.length,
			providerRoutes: snapshot?.providerRoutes ?? manifest.entities.providers.count,
			boards: snapshot?.boards ?? manifest.entities.boards.count,
			jobs: snapshot?.jobs ?? manifest.entities.jobs.count,
			openJobs:
				snapshot?.openJobs ??
				manifest.openJobCount ??
				manifest.entities.jobs.count,
		},
		top: {
			sourcesByJobs: topValuesFromSuggestions(
				manifest.suggestions?.sources,
				manifest.facets.sources,
			),
			providersByJobs: topValuesFromSuggestions(
				manifest.suggestions?.providers,
				manifest.facets.providerIds,
			),
			locations: topValuesFromSuggestions(
				manifest.suggestions?.locations,
				manifest.facets.locations,
			),
			departments: topValuesFromSuggestions(
				manifest.suggestions?.departments,
				manifest.facets.departments,
			),
			teams: topValuesFromSuggestions(manifest.suggestions?.teams, manifest.facets.teams),
			companies: topValuesFromSuggestions(
				manifest.suggestions?.companies,
				manifest.facets.companies,
			),
			skills: topValuesFromSuggestions(manifest.suggestions?.skills, manifest.facets.skills),
		},
		dataQuality: [],
		routeHealth: {
			supportLevels: topValuesFromSuggestions(undefined, manifest.facets.supportLevels),
			routeStatuses: topValuesFromSuggestions(undefined, manifest.facets.routeStatuses),
		},
		artifacts: {
			jobChunks:
				manifest.entities.jobs.chunks?.length ??
				Number(Boolean(manifest.entities.jobs.path || manifest.entities.jobs.initialPath)),
			detailShardBuckets: manifest.detailShards?.bucketCount ?? 0,
			detailShardRecords: manifest.detailShards?.count ?? 0,
		},
		fromGeneratedDashboard: false,
	};
}

function LineageSection({
	lineage,
	loading,
	onInspectRows,
	inspect,
}: {
	lineage: LineageAggregate | null;
	loading: boolean;
	onInspectRows: () => void;
	inspect: (entity: Entity, patch?: Partial<ExplorerFilters>) => void;
}) {
	if (!lineage) {
		if (loading) {
			return (
				<div
					className="min-w-0 overflow-hidden rounded-[var(--opps-radius-lg)] border border-border/75 bg-background/60"
					style={{ minHeight: LINEAGE_RESERVE_PX, ...explorerDeferredStyle(LINEAGE_RESERVE_PX) }}
					aria-busy="true"
				/>
			);
		}
		return (
			<ExplorerEmptyPanel
				heading="Lineage not in this snapshot"
				action={
					<Button type="button" variant="outline" size="sm" onClick={onInspectRows}>
						<FileSearch className="mr-2 size-4" width={16} height={16} aria-hidden="true" />
						Inspect rows
					</Button>
				}
			>
				<p>
					Lineage traces source → provider → board → job so snapshot coverage can
					be inspected end to end.
				</p>
				<pre className="mt-3 max-w-xl overflow-x-auto rounded-[var(--opps-radius-lg)] bg-foreground px-3 py-2 text-left font-mono text-xs text-background">
					{`just web-search-index`}
				</pre>
			</ExplorerEmptyPanel>
		);
	}
	return (
		<LazyMounted reservePx={LINEAGE_RESERVE_PX}>
			<LineageAnalysis lineage={lineage} inspect={inspect} />
		</LazyMounted>
	);
}

function LazyMounted({
	children,
	reservePx,
}: {
	children: ReactNode;
	reservePx: number;
}) {
	const ref = useRef<HTMLDivElement>(null);
	const [mounted, setMounted] = useState(false);

	useEffect(() => {
		const node = ref.current;
		if (!node || mounted) {
			return;
		}

		let finished = false;
		const mount = () => {
			if (finished) {
				return;
			}
			finished = true;
			startTransition(() => {
				setMounted(true);
			});
		};

		if (typeof IntersectionObserver === "undefined") {
			const id = window.setTimeout(mount, 0);
			return () => {
				finished = true;
				window.clearTimeout(id);
			};
		}

		const observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((entry) => entry.isIntersecting)) {
					mount();
				}
			},
			{ rootMargin: "280px 0px" },
		);
		observer.observe(node);

		const cancelIdle =
			typeof window.requestIdleCallback === "function"
				? (() => {
						const id = window.requestIdleCallback(mount, { timeout: 2200 });
						return () => window.cancelIdleCallback(id);
					})()
				: (() => {
						const id = window.setTimeout(mount, 2200);
						return () => window.clearTimeout(id);
					})();

		return () => {
			finished = true;
			observer.disconnect();
			cancelIdle();
		};
	}, [mounted]);

	return (
		<div
			ref={ref}
			className="min-w-0"
			style={{
				minHeight: mounted ? undefined : reservePx,
				...explorerDeferredStyle(reservePx),
			}}
		>
			{mounted ? children : null}
		</div>
	);
}

function LineageAnalysis({
	lineage,
	inspect,
}: {
	lineage: LineageAggregate;
	inspect: (entity: Entity, patch?: Partial<ExplorerFilters>) => void;
}) {
	const network = useMemo(() => buildLineageNetworkModel(lineage), [lineage]);
	return (
		<div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] [&>*]:min-w-0">
			<DashboardCard
				title="Full lineage map"
				icon={Network}
				description="Generated source rows, provider routes, boards, and job outcomes connected by lineage edges."
			>
				<LineageStageStrip model={network} />
				<div className="mt-4 min-w-0 border-t border-border/70 pt-3">
					<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
						Board job paths
					</h3>
					<LineagePathList rows={network.pathRows} maxJobs={network.maxPathJobs} inspect={inspect} />
				</div>
				<div className="mt-4 grid min-w-0 gap-3 md:grid-cols-2 [&>*]:min-w-0">
					<div className="min-w-0">
						<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
							Source-provider routes
						</h3>
						<LineagePairList
							rows={network.sourceProviderRows}
							maxJobs={network.maxSourceProviderJobs}
							emptyLabel="No source-provider lineage rows are available."
							metaLabel="routes"
							inspect={inspect}
						/>
					</div>
					<div className="min-w-0">
						<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
							Source-board reach
						</h3>
						<LineagePairList
							rows={network.sourceBoardRows}
							maxJobs={network.maxSourceBoardJobs}
							emptyLabel="No source-board lineage rows are available."
							metaLabel="boards"
							inspect={inspect}
						/>
					</div>
				</div>
			</DashboardCard>
			<DashboardCard
				title="Lineage diagnostics"
				icon={Route}
				description="Board completeness, freshness trail, and coverage gaps."
			>
				<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
					Board quality matrix
				</h3>
				<LineageQualityMatrix boards={lineage.nodes.boards} />
				<div className="mt-4 min-w-0 border-t border-border/70 pt-3">
					<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
						Freshness trail
					</h3>
					<LineageFreshness lineage={lineage} inspect={inspect} />
				</div>
				<div className="mt-4 min-w-0 border-t border-border/70 pt-3">
					<h3 className="mb-2 font-heading text-sm font-semibold tracking-normal">
						Coverage gaps
					</h3>
					<LineageGaps lineage={lineage} />
				</div>
			</DashboardCard>
		</div>
	);
}

function LineageStageStrip({ model }: { model: LineageNetworkModel }) {
	return (
		<div className="grid min-w-0 grid-cols-2 divide-x divide-y divide-border/70 border border-border/70 md:grid-cols-4 md:divide-y-0">
			{model.stages.map((stage) => (
				<div key={stage.key} className="min-w-0 px-3 py-2">
					<div className="font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
						{stage.label}
					</div>
					<div className="mt-1 font-heading text-xl font-semibold tracking-normal">
						{formatCount(stage.value)}
					</div>
					<div className="mt-1 text-xs text-muted-foreground">
						{formatCount(stage.secondaryValue)} {stage.secondaryLabel}
					</div>
					{stage.edgeLabel ? (
						<div className="mt-1 text-xs text-muted-foreground">
							{formatCount(stage.edgeCount)} {stage.edgeLabel}
						</div>
					) : null}
				</div>
			))}
		</div>
	);
}

function LineagePathList({
	rows,
	maxJobs,
	inspect,
}: {
	rows: LineagePathRow[];
	maxJobs: number;
	inspect: (entity: Entity, patch?: Partial<ExplorerFilters>) => void;
}) {
	if (rows.length === 0) {
		return <EmptyLineageState>No source-provider-board paths are available.</EmptyLineageState>;
	}
	return (
		<RankedLedgerList
			emptyLabel="No source-provider-board paths are available."
			items={rows.map((row) => ({
				key: row.key,
				label: `${row.sourceKey} -> ${row.providerId} -> ${row.boardKey}`,
				count: row.jobs,
				countLabel: `${formatCount(row.openJobs)} / ${formatCount(row.jobs)} open`,
				barPercent: coverageShare(row.jobs, maxJobs),
				snapshotPercent: row.openShare,
				innerPercent: row.openShare,
				onActivate: () =>
					inspect("jobs", { source: row.sourceKey, provider: row.providerId }),
				activateLabel: `Inspect lineage path ${row.sourceKey} -> ${row.providerId} -> ${row.boardKey}`,
			}))}
		/>
	);
}

function LineagePairList({
	rows,
	maxJobs,
	emptyLabel,
	metaLabel,
	inspect,
}: {
	rows: LineagePairRow[];
	maxJobs: number;
	emptyLabel: string;
	metaLabel: "routes" | "boards";
	inspect: (entity: Entity, patch?: Partial<ExplorerFilters>) => void;
}) {
	if (rows.length === 0) {
		return <EmptyLineageState>{emptyLabel}</EmptyLineageState>;
	}
	return (
		<RankedLedgerList
			emptyLabel={emptyLabel}
			items={rows.map((row) => {
				const metaValue = metaLabel === "routes" ? row.routes ?? 0 : row.boards ?? 0;
				const boardOnly = metaLabel === "boards";
				return {
					key: row.key,
					label: `${row.from} -> ${row.to}`,
					count: row.jobs,
					countLabel: `${formatCount(metaValue)} ${metaLabel} · ${formatCount(row.jobs)} jobs`,
					barPercent: coverageShare(row.jobs, maxJobs),
					snapshotPercent: row.openShare,
					tone: "info" as const,
					onActivate: boardOnly
						? () => inspect("jobs", { source: row.from })
						: () => inspect("jobs", { source: row.from, provider: row.to }),
					activateLabel: boardOnly
						? `Inspect jobs for source ${row.from}`
						: `Inspect jobs for ${row.from} / ${row.to}`,
				};
			})}
		/>
	);
}

function LineageQualityMatrix({ boards }: { boards: LineageAggregate["nodes"]["boards"] }) {
	const rows = boards.filter((board) => board.jobs > 0).slice(0, 8);
	if (rows.length === 0) {
		return <EmptyLineageState>No board quality rows are available.</EmptyLineageState>;
	}
	return (
		<div className="min-w-0 space-y-2">
			{rows.map((board) => (
				<div key={board.id} className="opps-provider-row min-w-0">
					<div className="min-w-0">
						<div className="flex items-center justify-between gap-3 text-xs">
							<span className="min-w-0 truncate font-semibold">
								{board.label || board.id}
							</span>
							<span className="shrink-0 font-mono tabular-nums tracking-normal text-muted-foreground">
								{formatCount(board.jobs)} jobs
							</span>
						</div>
						<div className="mt-2 grid min-w-0 gap-2 sm:grid-cols-3 [&>*]:min-w-0">
							<CoverageMeter
								label={`Desc ${board.quality?.description ?? 0}%`}
								percent={board.quality?.description ?? 0}
								tone="info"
							/>
							<CoverageMeter
								label={`Loc ${board.quality?.locations ?? 0}%`}
								percent={board.quality?.locations ?? 0}
								tone="info"
							/>
							<CoverageMeter
								label={`Comp ${board.quality?.compensation ?? 0}%`}
								percent={board.quality?.compensation ?? 0}
								tone={(board.quality?.compensation ?? 0) < 10 ? "warning" : "info"}
							/>
						</div>
					</div>
				</div>
			))}
		</div>
	);
}

function LineageFreshness({
	lineage,
	inspect,
}: {
	lineage: LineageAggregate;
	inspect: (entity: Entity, patch?: Partial<ExplorerFilters>) => void;
}) {
	const rows = [
		...lineage.nodes.sources.map((node) => ({ ...node, kind: "source" as const })),
		...lineage.nodes.providers.map((node) => ({ ...node, kind: "provider" as const })),
		...lineage.nodes.boards.map((node) => ({ ...node, kind: "board" as const })),
	]
		.filter((node) => node.latestObservedAt)
		.sort((left, right) =>
			String(right.latestObservedAt).localeCompare(String(left.latestObservedAt)),
		)
		.slice(0, 8);
	if (rows.length === 0) {
		return <EmptyLineageState>No freshness timestamps are available.</EmptyLineageState>;
	}
	return (
		<ul className="min-w-0 space-y-2">
			{rows.map((node) => {
				const label = node.label || node.id;
				const href =
					node.kind === "board" ? jobsBoardSearchHref({ q: label }) : undefined;
				const onActivate =
					node.kind === "source"
						? () => inspect("jobs", { source: node.id })
						: node.kind === "provider"
							? () => inspect("jobs", { provider: node.id })
							: undefined;
				const className =
					"opps-provider-row min-w-0 w-full hover:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40";
				const body = (
					<>
						<div className="min-w-0">
							<div className="font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
								{node.kind}
							</div>
							<div className="min-w-0 truncate font-semibold">{label}</div>
						</div>
						<span className="shrink-0 font-mono text-xs tabular-nums tracking-normal text-muted-foreground">
							{formatDate(node.latestObservedAt)}
						</span>
					</>
				);
				return (
					<li key={`${node.kind}-${node.id}`} className="min-w-0">
						{href ? (
							<Link href={href} className={className}>
								{body}
							</Link>
						) : (
							<button type="button" onClick={onActivate} className={cn(className, "text-left")}>
								{body}
							</button>
						)}
					</li>
				);
			})}
		</ul>
	);
}

function LineageGaps({ lineage }: { lineage: LineageAggregate }) {
	const boardsWithoutJobs = lineage.nodes.boards
		.filter((board) => (board.routes ?? 0) > 0 && board.jobs === 0)
		.slice(0, 4);
	const weakCompensation = lineage.nodes.boards
		.filter((board) => board.jobs > 0 && (board.quality?.compensation ?? 0) < 10)
		.slice(0, 4);
	const items: RankedLedgerItem[] = [
		...boardsWithoutJobs.map((board) => ({
			key: `empty-${board.id}`,
			label: board.label || board.id,
			count: board.routes ?? 0,
			countLabel: `${formatCount(board.routes)} routes / 0 jobs`,
			barPercent: 0,
			tone: "warning" as const,
			href: jobsBoardSearchHref({ q: board.label || board.id }),
			activateLabel: `Open ${board.label || board.id} on jobs board`,
		})),
		...weakCompensation.map((board) => ({
			key: `comp-${board.id}`,
			label: board.label || board.id,
			count: board.quality?.compensation ?? 0,
			countLabel: `${board.quality?.compensation ?? 0}% compensation coverage`,
			barPercent: board.quality?.compensation ?? 0,
			tone: "warning" as const,
			href: jobsBoardSearchHref({ q: board.label || board.id }),
			activateLabel: `Open ${board.label || board.id} on jobs board`,
		})),
	].slice(0, 8);
	if (items.length === 0) {
		return <EmptyLineageState>No high-priority lineage gaps in the aggregate.</EmptyLineageState>;
	}
	return <RankedLedgerList items={items} emptyLabel="No high-priority lineage gaps in the aggregate." />;
}

function EmptyLineageState({ children }: { children: ReactNode }) {
	return (
		<p className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 px-3 py-3 text-sm text-muted-foreground">
			{children}
		</p>
	);
}

function DashboardCard({
	title,
	description,
	icon: Icon = Activity,
	children,
}: {
	title: string;
	description?: string;
	icon?: ComponentType<SVGProps<SVGSVGElement>>;
	children: ReactNode;
}) {
	return (
		<section className="min-w-0 rounded-[var(--opps-radius-lg)] border border-border/75 bg-background/60 p-3 shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_5%,transparent)]">
			<div className="mb-3 flex items-start gap-2">
				<div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--opps-radius-md)] border border-primary/25 bg-primary/10 text-primary">
					<Icon className="size-4" width={16} height={16} aria-hidden="true" />
				</div>
				<div className="min-w-0">
					<h2 className="font-heading text-base font-semibold leading-snug tracking-normal">
						{title}
					</h2>
					{description ? (
						<p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
					) : null}
				</div>
			</div>
			{children}
		</section>
	);
}

function MetadataGrid({ items }: { items: Array<{ label: string; value: string }> }) {
	return (
		<div className="grid min-w-0 gap-2 sm:grid-cols-2 [&>*]:min-w-0">
			{items.map((item) => (
				<div
					key={item.label}
					className="min-w-0 rounded-[var(--opps-radius-md)] border border-border/70 px-3 py-2"
				>
					<div className="font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
						{item.label}
					</div>
					<div className="mt-1 truncate text-sm text-foreground">{item.value}</div>
				</div>
			))}
		</div>
	);
}

function QualityList({
	metrics,
	reserveCount = 0,
	busy = false,
}: {
	metrics: SearchDashboard["dataQuality"] | undefined;
	reserveCount?: number;
	busy?: boolean;
}) {
	const rows = (metrics ?? []).slice(0, 10);
	if (rows.length === 0) {
		if (reserveCount > 0) {
			return <RankedLedgerSkeleton count={reserveCount} />;
		}
		return (
			<p className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 px-3 py-3 text-sm text-muted-foreground">
				Data-quality aggregates are emitted by manifest v4 search-index builds.
			</p>
		);
	}
	return (
		<RankedLedgerList
			emptyLabel="Data-quality aggregates are emitted by manifest v4 search-index builds."
			reserveCount={reserveCount}
			busy={busy}
			items={rows.map((metric) => {
				const percentage = coverageShare(metric.count, metric.total) || clampPercent(metric.percentage);
				return {
					key: metric.key,
					label: humanizeKey(metric.key),
					count: metric.count,
					countLabel: `${formatCount(metric.count)} / ${formatCount(metric.total)} (${percentage}%)`,
					barPercent: percentage,
					tone: "info" as const,
				};
			})}
		/>
	);
}

function SuggestionStat({
	label,
	values,
	onActivate,
	hrefFor,
}: {
	label: string;
	values: SearchSuggestion[] | undefined;
	onActivate?: (value: string) => void;
	hrefFor?: (value: string) => string;
}) {
	const ranked = rankSuggestions(values, "", 1);
	const top = ranked[0];
	const topLabel = top?.label ?? top?.value ?? "none";
	const href = top && hrefFor ? hrefFor(top.value) : undefined;
	const interactive = Boolean((onActivate && top) || href);
	const body = (
		<>
			<div className="font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 text-sm font-semibold">{formatCount(values?.length)}</div>
			<div className="mt-0.5 truncate text-xs text-muted-foreground">{topLabel}</div>
		</>
	);
	const className = [
		"opps-metric min-w-0",
		interactive ? "hover:border-primary/45" : "",
	]
		.filter(Boolean)
		.join(" ");
	if (href) {
		return (
			<Link
				href={href}
				className={`${className} block`}
				aria-label={`Open ${label} ${topLabel} on jobs board`}
			>
				{body}
			</Link>
		);
	}
	if (onActivate && top) {
		return (
			<button
				type="button"
				onClick={() => onActivate(top.value)}
				className={`${className} w-full text-left`}
				aria-label={`Inspect ${label} for ${topLabel}`}
			>
				{body}
			</button>
		);
	}
	return <div className={className}>{body}</div>;
}

function routeHealthItems(
	values: SearchTopValue[] | undefined,
	snapshotTotal: number | undefined,
	onSelect: (value: string) => void,
): RankedLedgerItem[] {
	return rankedTopValueItems(values, {
		limit: 6,
		snapshotTotal,
		tone: "info",
		onSelect,
		inspectNoun: "providers",
	}).map((item) => ({
		...item,
		badge: item.label,
	}));
}

function topValuesFromSuggestions(
	suggestions: SearchSuggestion[] | undefined,
	fallbackValues: string[] | undefined,
): SearchTopValue[] {
	if (suggestions?.length) {
		return rankSuggestions(suggestions, "", 10).map((suggestion) => ({
			value: suggestion.value,
			count: suggestion.count,
		}));
	}
	return (fallbackValues ?? []).slice(0, 10).map((value) => ({ value, count: 0 }));
}

function labelMap(suggestions: SearchSuggestion[] | undefined) {
	if (!suggestions?.length) {
		return undefined;
	}
	return new Map(suggestions.map((suggestion) => [suggestion.value, suggestion.label]));
}

function countSuggestions(manifest: SearchManifest | null) {
	return Object.values(manifest?.suggestions ?? {}).reduce(
		(total, values) => total + (values?.length ?? 0),
		0,
	);
}

function humanizeKey(key: string) {
	return key
		.replace(/[_-]+/g, " ")
		.replace(/([a-z])([A-Z])/g, "$1 $2")
		.replace(/\b\w/g, (char) => char.toUpperCase());
}

function clampPercent(value: number) {
	if (!Number.isFinite(value)) {
		return 0;
	}
	return Math.max(0, Math.min(100, Math.round(value)));
}
