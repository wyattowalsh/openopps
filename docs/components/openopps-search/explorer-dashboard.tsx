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
import type { ComponentType, ReactNode, SVGProps } from "react";

import type {
	SearchDashboard,
	SearchManifest,
	SearchSuggestion,
	SearchTopValue,
} from "@/components/openopps-search/search-types";
import {
	formatCount,
	formatDate,
	rankSuggestions,
} from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

import { ExplorerMetric } from "./explorer-shared";

type ExplorerDashboardProps = {
	manifest: SearchManifest | null;
	loading: boolean;
	warning?: string | null;
	onInspectRows: () => void;
	onRetry?: () => void;
};

type DashboardModel = SearchDashboard & {
	fromGeneratedDashboard: boolean;
};

export function ExplorerDashboard({
	manifest,
	loading,
	warning,
	onInspectRows,
	onRetry,
}: ExplorerDashboardProps) {
	const dashboard = buildDashboardModel(manifest);
	const suggestionCount = countSuggestions(manifest);

	return (
		<div className="space-y-4">
			<div className="flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
				<div className="min-w-0">
					<p className="opps-kicker">OpenOppsDB explorer</p>
					<h1 className="mt-2 font-heading text-2xl font-semibold leading-tight md:text-3xl">
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
					<FileSearch className="mr-2 size-4" />
					Inspect rows
				</Button>
			</div>

			{warning ? (
				<div className="flex flex-col gap-2 rounded-[var(--opps-radius-lg)] border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning-foreground sm:flex-row sm:items-center sm:justify-between">
					<span>{warning}</span>
					{onRetry ? (
						<Button type="button" variant="outline" size="sm" onClick={onRetry}>
							Retry index
						</Button>
					) : null}
				</div>
			) : null}

			<div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
				<ExplorerMetric label="sources" value={dashboard?.totals.sourceRows} />
				<ExplorerMetric label="providers" value={dashboard?.totals.providerRoutes} />
				<ExplorerMetric label="boards" value={dashboard?.totals.boards} />
				<ExplorerMetric label="jobs" value={dashboard?.totals.jobs} />
				<ExplorerMetric label="open jobs" value={dashboard?.totals.openJobs} />
			</div>

			<div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
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
				</DashboardCard>
			</div>

			<div className="grid gap-3 xl:grid-cols-2">
				<DashboardCard
					title="Source coverage"
					icon={Globe2}
					description="Sources represented in the snapshot, ranked by generated job coverage when available."
				>
					<TopValuesList
						values={dashboard?.top.sourcesByJobs}
						labels={labelMap(manifest?.suggestions?.sources)}
						emptyLabel="Source coverage awaits the manifest v4 dashboard aggregate."
					/>
				</DashboardCard>
				<DashboardCard
					title="Provider coverage"
					icon={Network}
					description="Job-board providers and route families represented in the snapshot."
				>
					<TopValuesList
						values={dashboard?.top.providersByJobs}
						labels={labelMap(manifest?.suggestions?.providers)}
						emptyLabel="Provider coverage awaits the manifest v4 dashboard aggregate."
					/>
				</DashboardCard>
			</div>

			<div className="grid gap-3 xl:grid-cols-4">
				<DashboardCard title="Locations" icon={MapPin}>
					<TopValuesList
						values={dashboard?.top.locations}
						labels={labelMap(manifest?.suggestions?.locations)}
						emptyLabel="Location suggestions are not in this artifact yet."
						compact
					/>
				</DashboardCard>
				<DashboardCard title="Departments" icon={TableProperties}>
					<TopValuesList
						values={dashboard?.top.departments}
						labels={labelMap(manifest?.suggestions?.departments)}
						emptyLabel="Department suggestions are not in this artifact yet."
						compact
					/>
				</DashboardCard>
				<DashboardCard title="Companies" icon={LineChart}>
					<TopValuesList
						values={dashboard?.top.companies}
						labels={labelMap(manifest?.suggestions?.companies)}
						emptyLabel="Company suggestions are not in this artifact yet."
						compact
					/>
				</DashboardCard>
				<DashboardCard title="Skills" icon={Tags}>
					<TopValuesList
						values={dashboard?.top.skills}
						labels={labelMap(manifest?.suggestions?.skills)}
						emptyLabel="Skill suggestions are not in this artifact yet."
						compact
					/>
				</DashboardCard>
			</div>

			<div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
				<DashboardCard
					title="Data quality"
					icon={Sparkles}
					description="Completeness checks emitted by the search-index generator."
				>
					<QualityList metrics={dashboard?.dataQuality} />
				</DashboardCard>
				<DashboardCard
					title="Route health"
					icon={Route}
					description="Support and route-status distribution for provider routes."
				>
					<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
						<TopValuesList
							values={dashboard?.routeHealth.supportLevels}
							emptyLabel="Support-level counts are not in this artifact yet."
							compact
						/>
						<TopValuesList
							values={dashboard?.routeHealth.routeStatuses}
							emptyLabel="Route-status counts are not in this artifact yet."
							compact
						/>
					</div>
				</DashboardCard>
			</div>

			<DashboardCard
				title="Suggestion index"
				icon={BarChart3}
				description="Generated fuzzy-match surfaces available to search and filter controls."
			>
				<div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
					<SuggestionStat label="sources" values={manifest?.suggestions?.sources} />
					<SuggestionStat label="providers" values={manifest?.suggestions?.providers} />
					<SuggestionStat label="locations" values={manifest?.suggestions?.locations} />
					<SuggestionStat label="departments" values={manifest?.suggestions?.departments} />
					<SuggestionStat label="companies" values={manifest?.suggestions?.companies} />
					<SuggestionStat label="skills" values={manifest?.suggestions?.skills} />
					<SuggestionStat label="workplaces" values={manifest?.suggestions?.workplaces} />
					<SuggestionStat label="employment" values={manifest?.suggestions?.employmentTypes} />
				</div>
			</DashboardCard>
		</div>
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
		<section className="rounded-[var(--opps-radius-lg)] border border-border/75 bg-background/60 p-3 shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_5%,transparent)]">
			<div className="mb-3 flex items-start gap-2">
				<div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--opps-radius-md)] border border-primary/25 bg-primary/10 text-primary">
					<Icon className="size-4" />
				</div>
				<div className="min-w-0">
					<h2 className="font-heading text-base font-semibold leading-snug">
						{title}
					</h2>
					{description ? (
						<p className="mt-1 text-xs leading-5 text-muted-foreground">
							{description}
						</p>
					) : null}
				</div>
			</div>
			{children}
		</section>
	);
}

function MetadataGrid({ items }: { items: Array<{ label: string; value: string }> }) {
	return (
		<div className="grid gap-2 sm:grid-cols-2">
			{items.map((item) => (
				<div
					key={item.label}
					className="min-w-0 rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70 px-3 py-2"
				>
					<div className="font-mono text-[0.68rem] font-semibold text-muted-foreground">
						{item.label}
					</div>
					<div className="mt-1 truncate text-sm text-foreground">{item.value}</div>
				</div>
			))}
		</div>
	);
}

function TopValuesList({
	values,
	labels,
	emptyLabel,
	compact,
}: {
	values: SearchTopValue[] | undefined;
	labels?: Map<string, string>;
	emptyLabel: string;
	compact?: boolean;
}) {
	const rows = (values ?? []).filter((item) => item.value).slice(0, compact ? 6 : 8);
	const max = Math.max(1, ...rows.map((item) => item.count));
	if (rows.length === 0) {
		return (
			<div className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 bg-card/45 px-3 py-4 text-sm text-muted-foreground">
				{emptyLabel}
			</div>
		);
	}
	return (
		<div className="space-y-2">
			{rows.map((item) => {
				const width = `${Math.max(4, Math.round((item.count / max) * 100))}%`;
				const label = labels?.get(item.value) ?? item.value;
				return (
					<div key={item.value} className="space-y-1">
						<div className="flex items-center justify-between gap-3 text-xs">
							<span className="min-w-0 truncate font-semibold">{label}</span>
							<span className="font-mono text-muted-foreground">
								{formatCount(item.count)}
							</span>
						</div>
						<div className="h-2 overflow-hidden rounded-full bg-muted">
							<div
								className="h-full rounded-full bg-primary"
								style={{ width }}
								aria-hidden="true"
							/>
						</div>
					</div>
				);
			})}
		</div>
	);
}

function QualityList({ metrics }: { metrics: SearchDashboard["dataQuality"] | undefined }) {
	const rows = (metrics ?? []).slice(0, 10);
	if (rows.length === 0) {
		return (
			<div className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 bg-card/45 px-3 py-4 text-sm text-muted-foreground">
				Data-quality aggregates are emitted by manifest v4 search-index builds.
			</div>
		);
	}
	return (
		<div className="space-y-2">
			{rows.map((metric) => {
				const percentage = clampPercentage(metric.percentage);
				return (
					<div key={metric.key} className="space-y-1">
						<div className="flex items-center justify-between gap-3 text-xs">
							<span className="min-w-0 truncate font-semibold">
								{humanizeKey(metric.key)}
							</span>
							<span className="font-mono text-muted-foreground">
								{formatCount(metric.count)} / {formatCount(metric.total)} (
								{percentage}%)
							</span>
						</div>
						<div className="h-2 overflow-hidden rounded-full bg-muted">
							<div
								className="h-full rounded-full bg-info"
								style={{ width: `${Math.max(2, percentage)}%` }}
								aria-hidden="true"
							/>
						</div>
					</div>
				);
			})}
		</div>
	);
}

function SuggestionStat({
	label,
	values,
}: {
	label: string;
	values: SearchSuggestion[] | undefined;
}) {
	const ranked = rankSuggestions(values, "", 1);
	const top = ranked[0]?.label ?? ranked[0]?.value ?? "none";
	return (
		<div className="rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70 px-3 py-2">
			<div className="font-mono text-[0.68rem] font-semibold text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 text-sm font-semibold">{formatCount(values?.length)}</div>
			<div className="mt-0.5 truncate text-xs text-muted-foreground">{top}</div>
		</div>
	);
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

function clampPercentage(value: number) {
	if (!Number.isFinite(value)) {
		return 0;
	}
	return Math.max(0, Math.min(100, Math.round(value)));
}
