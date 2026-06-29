"use client";

import {
	BriefcaseBusiness,
	Building2,
	Database,
	ExternalLink,
	Filter,
	Loader2,
	Route,
	Search,
	X,
} from "lucide-react";
import {
	type ComponentType,
	type SVGProps,
	useDeferredValue,
	useEffect,
	useMemo,
	useState,
} from "react";

import {
	loadEntityChunk,
	loadSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	Entity,
	SearchChunk,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import { formatSalary } from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

type Filters = {
	query: string;
	source: string;
	provider: string;
	jobStatus: string;
	support: string;
	routeStatus: string;
	workplace: string;
	employment: string;
	location: string;
};

type SortKey =
	| "latest"
	| "relevance"
	| "title"
	| "company"
	| "name"
	| "provider"
	| "source"
	| "support"
	| "status";

const PAGE_SIZE = 50;

const P = {
	id: 0,
	source: 1,
	board: 2,
	provider: 3,
	label: 4,
	support: 5,
	count: 6,
	url: 7,
	status: 8,
} as const;

const B = {
	key: 0,
	source: 1,
	name: 2,
	domain: 3,
	url: 4,
	staff: 5,
	hint: 6,
} as const;

const J = {
	id: 0,
	source: 1,
	board: 2,
	provider: 3,
	status: 4,
	title: 5,
	company: 6,
	department: 7,
	team: 8,
	workplace: 9,
	remote: 10,
	type: 11,
	locations: 12,
	salaryMin: 13,
	salaryMax: 14,
	currency: 15,
	url: 16,
	posted: 17,
	latestObserved: 18,
} as const;

const ENTITY_OPTIONS: Array<{
	value: Entity;
	label: string;
	icon: ComponentType<SVGProps<SVGSVGElement>>;
}> = [
	{ value: "jobs", label: "Jobs", icon: BriefcaseBusiness },
	{ value: "boards", label: "Boards", icon: Building2 },
	{ value: "providers", label: "Board providers", icon: Route },
];

const SORT_OPTIONS: Record<Entity, Array<{ value: SortKey; label: string }>> = {
	jobs: [
		{ value: "latest", label: "Latest observed" },
		{ value: "relevance", label: "Relevance" },
		{ value: "company", label: "Company" },
		{ value: "title", label: "Title" },
		{ value: "provider", label: "Provider" },
		{ value: "status", label: "Status" },
	],
	boards: [
		{ value: "name", label: "Board name" },
		{ value: "source", label: "Source" },
	],
	providers: [
		{ value: "provider", label: "Provider" },
		{ value: "support", label: "Support" },
		{ value: "status", label: "Route status" },
		{ value: "source", label: "Source" },
	],
};

const DEFAULT_SORT: Record<Entity, SortKey> = {
	jobs: "latest",
	boards: "name",
	providers: "provider",
};

const DEFAULT_FILTERS: Filters = {
	query: "",
	source: "",
	provider: "",
	jobStatus: "open",
	support: "",
	routeStatus: "",
	workplace: "",
	employment: "",
	location: "",
};

export function OpenOppsSearchExplorer() {
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [chunks, setChunks] = useState<Partial<Record<Entity, SearchChunk>>>({});
	const [entity, setEntity] = useState<Entity>("jobs");
	const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
	const [sortKey, setSortKey] = useState<SortKey>(DEFAULT_SORT.jobs);
	const [visibleLimit, setVisibleLimit] = useState(PAGE_SIZE);
	const [loadingManifest, setLoadingManifest] = useState(true);
	const [loadingEntity, setLoadingEntity] = useState<Entity | null>(null);
	const [error, setError] = useState<string | null>(null);
	const deferredQuery = useDeferredValue(filters.query);
	const deferredLocation = useDeferredValue(filters.location);

	useEffect(() => {
		let mounted = true;

		async function loadManifest() {
			try {
				const nextManifest = await loadSearchManifest();
				if (mounted) {
					setManifest(nextManifest);
					setEntity(nextManifest.defaultEntity ?? "jobs");
					setSortKey(DEFAULT_SORT[nextManifest.defaultEntity ?? "jobs"]);
					setVisibleLimit(PAGE_SIZE);
					setFilters({
						...DEFAULT_FILTERS,
						jobStatus: nextManifest.defaultFilters?.jobs?.status ?? "open",
					});
					setError(null);
				}
			} catch (caught) {
				if (mounted) {
					setError(errorMessage(caught));
				}
			} finally {
				if (mounted) {
					setLoadingManifest(false);
				}
			}
		}

		loadManifest();
		return () => {
			mounted = false;
		};
	}, []);

	useEffect(() => {
		if (!manifest || chunks[entity]) {
			return;
		}
		const currentManifest = manifest;
		let mounted = true;

		async function loadChunk() {
			setLoadingEntity(entity);
			try {
				const nextChunk = await loadEntityChunk(currentManifest, entity);
				if (mounted) {
					setChunks((current) => ({ ...current, [entity]: nextChunk }));
					setError(null);
				}
			} catch (caught) {
				if (mounted) {
					setError(errorMessage(caught));
				}
			} finally {
				if (mounted) {
					setLoadingEntity(null);
				}
			}
		}

		loadChunk();
		return () => {
			mounted = false;
		};
	}, [chunks, entity, manifest]);

	const activeChunk = chunks[entity];
	const queryTerms = useMemo(() => terms(deferredQuery), [deferredQuery]);
	const locationTerms = useMemo(
		() => terms(deferredLocation),
		[deferredLocation],
	);
	const visibleRows = useMemo(() => {
		if (!activeChunk) {
			return [];
		}
		const rows = activeChunk.rows.filter((row) =>
			matchesRow(entity, row, filters, queryTerms, locationTerms),
		);
		return sortRows(entity, rows, sortKey, queryTerms);
	}, [activeChunk, entity, filters, locationTerms, queryTerms, sortKey]);

	const pageRows = visibleRows.slice(0, visibleLimit);
	const activeFilters = activeFilterCount(entity, filters);
	const isLoading = loadingManifest || loadingEntity === entity;
	const selectEntity = (nextEntity: Entity) => {
		setEntity(nextEntity);
		setSortKey(DEFAULT_SORT[nextEntity]);
		setVisibleLimit(PAGE_SIZE);
	};

	return (
		<section className="not-prose my-8 opps-ledger-shell">
			<div className="flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
				<div className="min-w-0">
					<p className="opps-kicker">OpenOppsDB search index</p>
					<h2 className="mt-2 font-heading text-2xl font-semibold leading-tight md:text-3xl">
						Boards, routes, and latest jobs
					</h2>
					<p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
						Static snapshot from{" "}
						<code>{manifest?.source.database ?? "kaggle/openoppsdb.sqlite"}</code>
						{manifest?.snapshotAt ? ` at ${formatDate(manifest.snapshotAt)}` : ""}
						.
					</p>
				</div>
				<div className="grid grid-cols-3 gap-2 sm:min-w-[28rem]">
					<Metric label="providers" value={manifest?.entities.providers.count} />
					<Metric label="boards" value={manifest?.entities.boards.count} />
					<Metric label="jobs" value={manifest?.entities.jobs.count} />
				</div>
			</div>

			<div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
				<div className="grid gap-2 sm:grid-cols-3">
					{ENTITY_OPTIONS.map((option) => {
						const Icon = option.icon;
						const active = option.value === entity;
						return (
							<button
								key={option.value}
								type="button"
								onClick={() => selectEntity(option.value)}
								className="opps-entity-tab"
								aria-pressed={active}
								data-active={active ? "true" : "false"}
								aria-label={`Show ${option.label}`}
							>
								<Icon className="size-4 shrink-0" />
								<span className="min-w-0 truncate">{option.label}</span>
								<span className="ml-auto font-mono text-xs opacity-75">
									{formatCount(manifest?.entities[option.value].count)}
								</span>
							</button>
						);
					})}
				</div>
				<div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
					<Database className="size-4" />
					<span>
						{formatCount(activeChunk?.count ?? manifest?.entities[entity].count)}{" "}
						indexed {entityLabel(entity)}
					</span>
				</div>
			</div>

			<div className="opps-toolbar mt-4">
				<div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(12rem,0.4fr)]">
					<label className="grid gap-1.5 text-sm font-semibold">
						<span className="flex items-center gap-2">
							<Search className="size-4" />
							Search
						</span>
						<input
							value={filters.query}
							onChange={(event) =>
								setFilters((current) => ({
									...current,
									query: event.target.value,
								}))
							}
							placeholder="company, title, board, provider, route"
							className="opps-input opps-input--search"
							aria-label="Search dataset"
						/>
					</label>
					<FilterSelect
						label="Sort"
						icon={Filter}
						value={sortKey}
						onChange={(value) => setSortKey(value as SortKey)}
						options={SORT_OPTIONS[entity]}
					/>
				</div>

				<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
					<FilterSelect
						label="Source"
						value={filters.source}
						onChange={(value) =>
							setFilters((current) => ({ ...current, source: value }))
						}
						options={facetOptions(manifest?.facets.sources)}
					/>
					{entity !== "boards" ? (
						<FilterSelect
							label="Provider"
							value={filters.provider}
							onChange={(value) =>
								setFilters((current) => ({ ...current, provider: value }))
							}
							options={facetOptions(manifest?.facets.providerIds)}
						/>
					) : null}
					{entity === "jobs" ? (
						<>
							<FilterSelect
								label="Job status"
								value={filters.jobStatus}
								onChange={(value) =>
									setFilters((current) => ({
										...current,
										jobStatus: value,
									}))
								}
								options={facetOptions(manifest?.facets.jobStatuses)}
							/>
							<FilterSelect
								label="Workplace"
								value={filters.workplace}
								onChange={(value) =>
									setFilters((current) => ({
										...current,
										workplace: value,
									}))
								}
								options={facetOptions(manifest?.facets.workplaces)}
							/>
							<FilterSelect
								label="Employment"
								value={filters.employment}
								onChange={(value) =>
									setFilters((current) => ({
										...current,
										employment: value,
									}))
								}
								options={facetOptions(manifest?.facets.employmentTypes)}
							/>
							<label className="grid gap-1.5 text-sm font-semibold">
								<span>Location</span>
								<input
									value={filters.location}
									onChange={(event) =>
										setFilters((current) => ({
											...current,
											location: event.target.value,
										}))
									}
									placeholder="city, country, remote"
									className="opps-input"
									aria-label="Location"
								/>
							</label>
						</>
					) : null}
					{entity === "providers" ? (
						<>
							<FilterSelect
								label="Support"
								value={filters.support}
								onChange={(value) =>
									setFilters((current) => ({ ...current, support: value }))
								}
								options={facetOptions(manifest?.facets.supportLevels)}
							/>
							<FilterSelect
								label="Route status"
								value={filters.routeStatus}
								onChange={(value) =>
									setFilters((current) => ({
										...current,
										routeStatus: value,
									}))
								}
								options={facetOptions(manifest?.facets.routeStatuses)}
							/>
						</>
					) : null}
				</div>

				<div className="flex flex-col gap-3 border-t border-border/70 pt-3 md:flex-row md:items-center md:justify-between">
					<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
						<span className="font-semibold text-foreground">
							{formatCount(visibleRows.length)} matches
						</span>
						{activeFilters > 0 ? (
							<span>{activeFilters} active filters</span>
						) : (
							<span>default view</span>
						)}
						{filters.jobStatus === "open" && entity === "jobs" ? (
							<span className="openopps-status-chip" data-tone="jobs">
								open
							</span>
						) : null}
					</div>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={() => {
							setFilters(DEFAULT_FILTERS);
							setVisibleLimit(PAGE_SIZE);
						}}
					>
						<X className="mr-2 size-3.5" />
						Clear filters
					</Button>
				</div>
			</div>

			{error ? <ErrorPanel message={error} /> : null}
			{isLoading ? <LoadingPanel entity={entity} /> : null}
			{!isLoading && !error ? (
				<ResultList
					entity={entity}
					rows={pageRows}
					total={visibleRows.length}
					visibleLimit={visibleLimit}
					onMore={() => setVisibleLimit((current) => current + PAGE_SIZE)}
				/>
			) : null}
		</section>
	);
}

function Metric({ label, value }: { label: string; value?: number }) {
	return (
		<div className="opps-metric">
			<div className="font-heading text-xl font-semibold text-primary">
				{formatCount(value)}
			</div>
			<div className="mt-1 truncate font-mono text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
				{label}
			</div>
		</div>
	);
}

function FilterSelect({
	label,
	value,
	onChange,
	options,
	icon: Icon,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	options: Array<{ value: string; label: string }>;
	icon?: ComponentType<SVGProps<SVGSVGElement>>;
}) {
	return (
		<label className="grid gap-1.5 text-sm font-semibold">
			<span className="flex items-center gap-2">
				{Icon ? <Icon className="size-4" /> : null}
				{label}
			</span>
			<select
				value={value}
				onChange={(event) => onChange(event.target.value)}
				className="opps-select"
				aria-label={label}
			>
				{options.map((option) => (
					<option key={`${label}-${option.value}`} value={option.value}>
						{option.label}
					</option>
				))}
			</select>
		</label>
	);
}

function ResultList({
	entity,
	rows,
	total,
	visibleLimit,
	onMore,
}: {
	entity: Entity;
	rows: SearchRow[];
	total: number;
	visibleLimit: number;
	onMore: () => void;
}) {
	if (rows.length === 0) {
		return (
			<div className="opps-empty mt-4 text-sm text-muted-foreground">
				No {entityLabel(entity)} match the current filters.
			</div>
		);
	}

	return (
		<div className="mt-4 space-y-3">
			{rows.map((row) => {
				if (entity === "jobs") {
					return <JobResult key={text(row[J.id])} row={row} />;
				}
				if (entity === "boards") {
					return <BoardResult key={text(row[B.key])} row={row} />;
				}
				return <ProviderResult key={text(row[P.id])} row={row} />;
			})}
			{visibleLimit < total ? (
				<div className="flex justify-center pt-2">
					<Button type="button" variant="outline" onClick={onMore}>
						Show {formatCount(Math.min(PAGE_SIZE, total - visibleLimit))} more
					</Button>
				</div>
			) : null}
		</div>
	);
}

function JobResult({ row }: { row: SearchRow }) {
	return (
		<article className="opps-result-card">
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<span
							className="openopps-status-chip"
							data-tone={text(row[J.status]) === "open" ? "jobs" : "unsupported"}
						>
							{text(row[J.status]) || "unknown"}
						</span>
						<span className="font-mono text-xs text-muted-foreground">
							{text(row[J.provider]) || "provider"} /{" "}
							{text(row[J.source]) || "source"}
						</span>
					</div>
					<h3 className="mt-3 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[J.title]) || "Untitled role"}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">
						{text(row[J.company]) || text(row[J.board])}
					</p>
				</div>
				<ResultLink href={text(row[J.url])} label="Posting" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
				<Field label="Location" value={formatLocations(row[J.locations])} />
				<Field
					label="Workplace"
					value={[text(row[J.workplace]), text(row[J.remote])]
						.filter(Boolean)
						.join(" / ")}
				/>
				<Field label="Type" value={text(row[J.type])} />
				<Field label="Observed" value={formatDate(text(row[J.latestObserved]))} />
				<Field
					label="Team"
					value={[text(row[J.department]), text(row[J.team])]
						.filter(Boolean)
						.join(" / ")}
				/>
				<Field label="Salary" value={formatSalary(row)} />
				<Field label="Board" value={text(row[J.board])} />
				<Field label="Posted" value={formatDate(text(row[J.posted]))} />
			</div>
		</article>
	);
}

function BoardResult({ row }: { row: SearchRow }) {
	return (
		<article className="opps-result-card">
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<p className="font-mono text-xs text-muted-foreground">
						{text(row[B.source]) || "source"} / {text(row[B.key])}
					</p>
					<h3 className="mt-2 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[B.name]) || text(row[B.domain]) || text(row[B.key])}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">{text(row[B.domain])}</p>
				</div>
				<ResultLink href={text(row[B.url])} label="Board" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
				<Field label="Staff" value={formatNullableNumber(row[B.staff])} />
				<Field label="Jobs hint" value={formatNullableNumber(row[B.hint])} />
				<Field label="Source" value={text(row[B.source])} />
			</div>
		</article>
	);
}

function ProviderResult({ row }: { row: SearchRow }) {
	return (
		<article className="opps-result-card">
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<span className="openopps-status-chip" data-tone={text(row[P.support])}>
							{text(row[P.support]) || "unknown"}
						</span>
						{text(row[P.status]) ? (
							<span className="openopps-status-chip" data-tone={text(row[P.status])}>
								{text(row[P.status])}
							</span>
						) : null}
					</div>
					<h3 className="mt-3 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[P.label]) || text(row[P.provider])}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">
						{text(row[P.provider])} route for {text(row[P.board])}
					</p>
				</div>
				<ResultLink href={text(row[P.url])} label="Route" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-4">
				<Field label="Source" value={text(row[P.source])} />
				<Field label="Provider" value={text(row[P.provider])} />
				<Field label="Jobs hint" value={formatNullableNumber(row[P.count])} />
				<Field label="Route id" value={text(row[P.id])} />
			</div>
		</article>
	);
}

function Field({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-xl border border-border/60 bg-card/65 px-3 py-2">
			<div className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 min-h-5 truncate text-foreground">{value || "n/a"}</div>
		</div>
	);
}

function ResultLink({ href, label }: { href: string; label: string }) {
	if (!href) {
		return null;
	}
	return (
		<a
			href={href}
			target="_blank"
			rel="noreferrer"
			className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-[var(--opps-radius-md)] border border-border bg-card px-3 text-sm font-semibold text-foreground transition hover:border-primary/50 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
			aria-label={`Open ${label} in new tab`}
		>
			{label}
			<ExternalLink className="size-3.5" />
		</a>
	);
}

function LoadingPanel({ entity }: { entity: Entity }) {
	return (
		<div className="mt-4 flex items-center gap-3 rounded-2xl border border-border/75 bg-background/55 p-5 text-sm text-muted-foreground">
			<Loader2 className="size-4 animate-spin text-primary" />
			Loading {entityLabel(entity)}.
		</div>
	);
}

function ErrorPanel({ message }: { message: string }) {
	return (
		<div className="mt-4 rounded-2xl border border-destructive/45 bg-destructive/10 p-5 text-sm text-destructive">
			{message}
		</div>
	);
}

function matchesRow(
	entity: Entity,
	row: SearchRow,
	filters: Filters,
	queryTerms: string[],
	locationTerms: string[],
) {
	if (queryTerms.length > 0 && !matchesTerms(searchText(entity, row), queryTerms)) {
		return false;
	}
	if (filters.source && sourceValue(entity, row) !== filters.source) {
		return false;
	}
	if (
		filters.provider &&
		entity !== "boards" &&
		providerValue(entity, row) !== filters.provider
	) {
		return false;
	}
	if (entity === "jobs") {
		if (filters.jobStatus && text(row[J.status]) !== filters.jobStatus) {
			return false;
		}
		if (
			filters.workplace &&
			text(row[J.workplace]) !== filters.workplace &&
			text(row[J.remote]) !== filters.workplace
		) {
			return false;
		}
		if (filters.employment && text(row[J.type]) !== filters.employment) {
			return false;
		}
		if (
			locationTerms.length > 0 &&
			!matchesTerms(normalize(text(row[J.locations])), locationTerms)
		) {
			return false;
		}
	}
	if (entity === "providers") {
		if (filters.support && text(row[P.support]) !== filters.support) {
			return false;
		}
		if (filters.routeStatus && text(row[P.status]) !== filters.routeStatus) {
			return false;
		}
	}
	return true;
}

function sortRows(
	entity: Entity,
	rows: SearchRow[],
	sortKey: SortKey,
	queryTerms: string[],
) {
	return [...rows].sort((left, right) => {
		if (sortKey === "relevance" && queryTerms.length > 0) {
			return (
				relevanceScore(entity, right, queryTerms) -
					relevanceScore(entity, left, queryTerms) ||
				compareEntityFallback(entity, left, right)
			);
		}
		if (entity === "jobs") {
			if (sortKey === "latest") {
				return compareLatestObserved(left, right);
			}
			if (sortKey === "company") {
				return compareText(text(left[J.company]), text(right[J.company]));
			}
			if (sortKey === "title") {
				return compareText(text(left[J.title]), text(right[J.title]));
			}
			if (sortKey === "provider") {
				return compareText(text(left[J.provider]), text(right[J.provider]));
			}
			if (sortKey === "status") {
				return compareText(text(left[J.status]), text(right[J.status]));
			}
		}
		if (entity === "boards") {
			if (sortKey === "source") {
				return compareText(text(left[B.source]), text(right[B.source]));
			}
			return compareText(text(left[B.name] || left[B.key]), text(right[B.name] || right[B.key]));
		}
		if (sortKey === "support") {
			return compareText(text(left[P.support]), text(right[P.support]));
		}
		if (sortKey === "status") {
			return compareText(text(left[P.status]), text(right[P.status]));
		}
		if (sortKey === "source") {
			return compareText(text(left[P.source]), text(right[P.source]));
		}
		return compareText(text(left[P.provider]), text(right[P.provider]));
	});
}

function compareEntityFallback(entity: Entity, left: SearchRow, right: SearchRow) {
	if (entity === "jobs") {
		return (
			compareLatestObserved(left, right) ||
			compareText(text(left[J.title]), text(right[J.title]))
		);
	}
	if (entity === "boards") {
		return compareText(text(left[B.name]), text(right[B.name]));
	}
	return compareText(text(left[P.provider]), text(right[P.provider]));
}

function searchText(entity: Entity, row: SearchRow) {
	if (entity === "jobs") {
		return normalize(
			[
				row[J.title],
				row[J.company],
				row[J.department],
				row[J.team],
				row[J.locations],
				row[J.provider],
				row[J.source],
				row[J.board],
			].join(" "),
		);
	}
	if (entity === "boards") {
		return normalize([row[B.name], row[B.domain], row[B.key], row[B.source], row[B.url]].join(" "));
	}
	return normalize(
		[
			row[P.label],
			row[P.provider],
			row[P.board],
			row[P.source],
			row[P.url],
			row[P.status],
		].join(" "),
	);
}

function relevanceScore(entity: Entity, row: SearchRow, queryTerms: string[]) {
	const haystack = searchText(entity, row);
	let score = 0;
	for (const term of queryTerms) {
		if (haystack.startsWith(term)) {
			score += 3;
		} else if (haystack.includes(` ${term}`)) {
			score += 2;
		} else if (haystack.includes(term)) {
			score += 1;
		}
	}
	return score;
}

function sourceValue(entity: Entity, row: SearchRow) {
	if (entity === "jobs") {
		return text(row[J.source]);
	}
	if (entity === "boards") {
		return text(row[B.source]);
	}
	return text(row[P.source]);
}

function providerValue(entity: Entity, row: SearchRow) {
	if (entity === "jobs") {
		return text(row[J.provider]);
	}
	return text(row[P.provider]);
}

function activeFilterCount(entity: Entity, filters: Filters) {
	let count = Number(Boolean(filters.query)) + Number(Boolean(filters.source));
	if (entity !== "boards") {
		count += Number(Boolean(filters.provider));
	}
	if (entity === "jobs") {
		count +=
			Number(Boolean(filters.jobStatus && filters.jobStatus !== "open")) +
			Number(Boolean(filters.workplace)) +
			Number(Boolean(filters.employment)) +
			Number(Boolean(filters.location));
	}
	if (entity === "providers") {
		count += Number(Boolean(filters.support)) + Number(Boolean(filters.routeStatus));
	}
	return count;
}

function facetOptions(values: string[] | undefined) {
	return [
		{ value: "", label: "Any" },
		...(values ?? []).map((value) => ({ value, label: value })),
	];
}

function terms(value: string) {
	return normalize(value).split(/\s+/).filter(Boolean);
}

function matchesTerms(value: string, queryTerms: string[]) {
	return queryTerms.every((term) => value.includes(term));
}

function normalize(value: string) {
	return value.toLowerCase().trim();
}

function text(value: unknown) {
	if (value === null || value === undefined) {
		return "";
	}
	return String(value).trim();
}

function compareText(left: string, right: string) {
	return left.localeCompare(right, undefined, {
		numeric: true,
		sensitivity: "base",
	});
}

function formatCount(value: number | undefined) {
	if (value === undefined) {
		return "0";
	}
	return new Intl.NumberFormat("en-US").format(value);
}

function formatNullableNumber(value: unknown) {
	if (value === null || value === undefined || value === "") {
		return "";
	}
	const numeric = Number(value);
	if (!Number.isFinite(numeric)) {
		return "";
	}
	return formatCount(numeric);
}

function formatDate(value: string) {
	if (!value) {
		return "";
	}
	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) {
		return value;
	}
	return new Intl.DateTimeFormat("en-US", {
		year: "numeric",
		month: "short",
		day: "numeric",
	}).format(parsed);
}

function formatLocations(value: unknown) {
	const raw = text(value);
	if (!raw) {
		return "";
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		if (Array.isArray(parsed)) {
			return parsed.map((item) => text(item)).filter(Boolean).join(", ");
		}
	} catch {
		return raw;
	}
	return raw;
}

function entityLabel(entity: Entity) {
	if (entity === "providers") {
		return "board providers";
	}
	return entity;
}

function errorMessage(caught: unknown) {
	if (caught instanceof Error) {
		return caught.message;
	}
	return "Unable to load the OpenOpps search index.";
}

function compareLatestObserved(left: SearchRow, right: SearchRow) {
	const leftTime = timestampValue(rowLatestObserved(left));
	const rightTime = timestampValue(rowLatestObserved(right));
	if (leftTime !== rightTime) {
		return rightTime - leftTime;
	}
	return compareText(rowLatestObserved(right), rowLatestObserved(left));
}

function rowLatestObserved(row: SearchRow) {
	return text(row[J.latestObserved]);
}

function timestampValue(value: string) {
	if (!value) {
		return Number.NEGATIVE_INFINITY;
	}
	const parsed = Date.parse(value);
	return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}
