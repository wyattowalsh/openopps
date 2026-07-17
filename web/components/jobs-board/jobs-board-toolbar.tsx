"use client";

import {
	BookmarkPlus,
	CheckCheck,
	ChevronDown,
	Copy,
	EyeOff,
	Filter,
	RotateCcw,
	Search,
	Settings2,
	SlidersHorizontal,
	Trash2,
	X,
} from "lucide-react";
import { useId, useMemo } from "react";

import type { JobBoardFilters } from "@/components/jobs-board/jobs-board-filter-engine";
import type { SavedSearchRecord } from "@/components/jobs-board/jobs-board-local-state";
import type {
	SearchManifest,
	SearchSuggestion,
} from "@/components/openopps-search/search-types";
import {
	formatCount,
	normalizeSuggestion,
	rankSuggestions,
} from "@/components/openopps-search/search-utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export const JOBS_BOARD_WIDE_SEARCH_DESC_ID = "jobs-board-wide-search-desc";

type JobsBoardToolbarProps = {
	filters: JobBoardFilters;
	manifest: SearchManifest | null;
	matchCount: number;
	searchActive: boolean;
	activeFilterCount: number;
	showHidden: boolean;
	savedSearches: Array<{
		record: SavedSearchRecord;
		newMatches: number | null;
	}>;
	onChange: (next: Partial<JobBoardFilters>) => void;
	onClear: () => void;
	onShowHiddenChange: (showHidden: boolean) => void;
	onSaveSearch: () => void;
	onRestoreSavedSearch: (record: SavedSearchRecord) => void;
	onDeleteSavedSearch: (record: SavedSearchRecord) => void;
	onDuplicateSavedSearch: (record: SavedSearchRecord) => void;
	onReviewSavedSearch: (record: SavedSearchRecord) => void;
	onOpenLocalData: () => void;
};

type StringFilterKey = {
	[K in keyof JobBoardFilters]: JobBoardFilters[K] extends string ? K : never;
}[keyof JobBoardFilters];

type FilterChip = {
	key: keyof JobBoardFilters;
	label: string;
	value: string;
};

const FILTER_LABELS = {
	query: "Search",
	wide: "Wide",
	includeAllIndexed: "All indexed",
	source: "Source",
	provider: "Provider",
	location: "Location",
	department: "Department",
	team: "Team",
	workplace: "Workplace",
	remote: "Remote",
	employment: "Employment",
	skill: "Skill",
	salaryMin: "Salary min",
	salaryMax: "Salary max",
	postedAfter: "Posted after",
	postedBefore: "Posted before",
} satisfies Record<keyof JobBoardFilters, string>;

const REMOTE_SUGGESTIONS = suggestionsFromValues([
	"remote",
	"hybrid",
	"onsite",
	"on-site",
]);

export function activeFilterChips(filters: JobBoardFilters): FilterChip[] {
	const chips: FilterChip[] = [];
	for (const key of Object.keys(FILTER_LABELS) as Array<keyof JobBoardFilters>) {
		const value = filters[key];
		if (typeof value === "boolean") {
			if (value) {
				chips.push({
					key,
					label: FILTER_LABELS[key],
					value: "enabled",
				});
			}
			continue;
		}
		if (!value) {
			continue;
		}
		chips.push({
			key,
			label: FILTER_LABELS[key],
			value: formatChipValue(key, value),
		});
	}
	return chips;
}

export function removeFilterPatch(
	key: keyof JobBoardFilters,
): Partial<JobBoardFilters> {
	if (key === "wide" || key === "includeAllIndexed") {
		return { [key]: false } as Partial<JobBoardFilters>;
	}
	return { [key]: "" } as Partial<JobBoardFilters>;
}

function formatChipValue(key: keyof JobBoardFilters, value: string) {
	if (key === "salaryMin" || key === "salaryMax") {
		const number = Number(value);
		if (Number.isFinite(number)) {
			return new Intl.NumberFormat("en-US", {
				style: "currency",
				currency: "USD",
				maximumFractionDigits: 0,
			}).format(number);
		}
	}
	return value;
}

function suggestionsFromValues(values: string[] | undefined): SearchSuggestion[] {
	return (values ?? [])
		.filter(Boolean)
		.map((value) => ({
			value,
			label: value,
			count: 0,
			normalized: normalizeSuggestion(value),
		}));
}

function rankedOptions(
	suggestions: SearchSuggestion[] | undefined,
	query: string,
) {
	return rankSuggestions(suggestions, query, 10);
}

function suggestionsFor(
	manifest: SearchManifest | null,
	key: StringFilterKey,
): SearchSuggestion[] {
	switch (key) {
		case "source":
			return manifest?.suggestions?.sources ?? suggestionsFromValues(manifest?.facets.sources);
		case "provider":
			return (
				manifest?.suggestions?.providers ??
				suggestionsFromValues(manifest?.facets.providerIds)
			);
		case "location":
			return (
				manifest?.suggestions?.locations ??
				suggestionsFromValues(manifest?.facets.locations)
			);
		case "department":
			return (
				manifest?.suggestions?.departments ??
				suggestionsFromValues(manifest?.facets.departments)
			);
		case "team":
			return manifest?.suggestions?.teams ?? suggestionsFromValues(manifest?.facets.teams);
		case "workplace":
			return (
				manifest?.suggestions?.workplaces ??
				suggestionsFromValues(manifest?.facets.workplaces)
			);
		case "employment":
			return (
				manifest?.suggestions?.employmentTypes ??
				suggestionsFromValues(manifest?.facets.employmentTypes)
			);
		case "skill":
			return manifest?.suggestions?.skills ?? suggestionsFromValues(manifest?.facets.skills);
		case "remote":
			return REMOTE_SUGGESTIONS;
		default:
			return [];
	}
}

function SuggestionInput({
	label,
	value,
	onChange,
	suggestions,
	placeholder,
	type = "text",
	className,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	suggestions?: SearchSuggestion[];
	placeholder?: string;
	type?: string;
	className?: string;
}) {
	const inputId = useId();
	const listId = `${inputId}-suggestions`;
	const options = useMemo(
		() => rankedOptions(suggestions, value),
		[suggestions, value],
	);

	return (
		<label className={cn("grid min-w-0 gap-1.5 text-xs font-semibold", className)}>
			<span className="text-muted-foreground">{label}</span>
			<input
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				className="opps-input h-8"
				aria-label={label}
				list={type === "text" && options.length > 0 ? listId : undefined}
			/>
			{type === "text" && options.length > 0 ? (
				<datalist id={listId}>
					{options.map((option) => (
						<option
							key={`${listId}-${option.value}`}
							value={option.value}
							label={
								option.count > 0
									? `${option.label} (${formatCount(option.count)})`
									: option.label
							}
						/>
					))}
				</datalist>
			) : null}
		</label>
	);
}

export function JobsBoardToolbar({
	filters,
	manifest,
	matchCount,
	searchActive,
	activeFilterCount,
	showHidden,
	savedSearches,
	onChange,
	onClear,
	onShowHiddenChange,
	onSaveSearch,
	onRestoreSavedSearch,
	onDeleteSavedSearch,
	onDuplicateSavedSearch,
	onReviewSavedSearch,
	onOpenLocalData,
}: JobsBoardToolbarProps) {
	const chips = activeFilterChips(filters);
	const updateStringFilter = (key: StringFilterKey, value: string) => {
		onChange({ [key]: value } as Partial<JobBoardFilters>);
	};
	const removeFilter = (key: keyof JobBoardFilters) => {
		onChange(removeFilterPatch(key));
	};

	return (
		<TooltipProvider>
			<div className="opps-toolbar space-y-3">
				<div className="grid gap-3 lg:grid-cols-[minmax(16rem,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_auto]">
					<label className="grid gap-1.5 text-xs font-semibold">
						<span className="flex items-center gap-2 text-muted-foreground">
							<Search className="size-3.5" />
							Search
						</span>
						<input
							value={filters.query}
							onChange={(event) => onChange({ query: event.target.value })}
							placeholder="title, company, description"
							className="opps-input opps-input--search h-8"
							aria-label="Search jobs"
						/>
					</label>
					<SuggestionInput
						label="Source"
						value={filters.source}
						onChange={(value) => updateStringFilter("source", value)}
						suggestions={suggestionsFor(manifest, "source")}
						placeholder="any source"
					/>
					<SuggestionInput
						label="Provider"
						value={filters.provider}
						onChange={(value) => updateStringFilter("provider", value)}
						suggestions={suggestionsFor(manifest, "provider")}
						placeholder="greenhouse, lever"
					/>
					<div className="flex items-end gap-2">
						<Tooltip>
							<TooltipTrigger asChild>
								<Button
									type="button"
									variant={filters.wide ? "secondary" : "outline"}
									size="sm"
									onClick={() => onChange({ wide: !filters.wide })}
									aria-pressed={filters.wide}
									aria-describedby={JOBS_BOARD_WIDE_SEARCH_DESC_ID}
								>
									<Filter className="size-3.5" />
									Wide
								</Button>
							</TooltipTrigger>
							<TooltipContent id={JOBS_BOARD_WIDE_SEARCH_DESC_ID}>
								Search department, team, locations, provider, board, and source
								fields too.
							</TooltipContent>
						</Tooltip>
						<Tooltip>
							<TooltipTrigger asChild>
								<Button
									type="button"
									variant={filters.includeAllIndexed ? "secondary" : "outline"}
									size="sm"
									onClick={() =>
										onChange({ includeAllIndexed: !filters.includeAllIndexed })
									}
									aria-pressed={filters.includeAllIndexed}
								>
									<Filter className="size-3.5" />
									All
								</Button>
							</TooltipTrigger>
							<TooltipContent>
								Include closed and non-open indexed jobs in results.
							</TooltipContent>
						</Tooltip>
						<Tooltip>
							<TooltipTrigger asChild>
									<Button
										type="button"
										variant="outline"
										size="icon-sm"
										onClick={onSaveSearch}
										disabled={activeFilterCount === 0}
										aria-label="Save current search"
									>
									<BookmarkPlus className="size-3.5" />
								</Button>
							</TooltipTrigger>
							<TooltipContent>Save current search locally.</TooltipContent>
						</Tooltip>
						<Tooltip>
							<TooltipTrigger asChild>
								<Button
									type="button"
									variant={showHidden ? "secondary" : "outline"}
									size="icon-sm"
									onClick={() => onShowHiddenChange(!showHidden)}
									aria-pressed={showHidden}
									aria-label="Show hidden jobs"
								>
									<EyeOff className="size-3.5" />
								</Button>
							</TooltipTrigger>
							<TooltipContent>
								{showHidden ? "Hidden jobs are visible." : "Show hidden jobs."}
							</TooltipContent>
						</Tooltip>
						<Tooltip>
							<TooltipTrigger asChild>
								<Button
									type="button"
									variant="outline"
									size="icon-sm"
									onClick={onOpenLocalData}
									aria-label="Open app settings"
								>
									<Settings2 className="size-3.5" />
								</Button>
							</TooltipTrigger>
							<TooltipContent>App settings and local data.</TooltipContent>
						</Tooltip>
					</div>
				</div>

				<details className="group rounded-[var(--opps-radius-md)] border border-border/70 bg-background/55">
					<summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-muted-foreground">
						<span className="inline-flex items-center gap-2">
							<SlidersHorizontal className="size-3.5" />
							More filters
						</span>
						<ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
					</summary>
					<div className="grid gap-3 border-t border-border/70 p-3 md:grid-cols-2 xl:grid-cols-4">
						<SuggestionInput
							label="Location"
							value={filters.location}
							onChange={(value) => updateStringFilter("location", value)}
							suggestions={suggestionsFor(manifest, "location")}
							placeholder="city, country, remote"
						/>
						<SuggestionInput
							label="Department"
							value={filters.department}
							onChange={(value) => updateStringFilter("department", value)}
							suggestions={suggestionsFor(manifest, "department")}
							placeholder="engineering, sales"
						/>
						<SuggestionInput
							label="Team"
							value={filters.team}
							onChange={(value) => updateStringFilter("team", value)}
							suggestions={suggestionsFor(manifest, "team")}
							placeholder="platform, growth"
						/>
						<SuggestionInput
							label="Skill"
							value={filters.skill}
							onChange={(value) => updateStringFilter("skill", value)}
							suggestions={suggestionsFor(manifest, "skill")}
							placeholder="python, kubernetes"
						/>
						<SuggestionInput
							label="Workplace"
							value={filters.workplace}
							onChange={(value) => updateStringFilter("workplace", value)}
							suggestions={suggestionsFor(manifest, "workplace")}
							placeholder="remote, hybrid"
						/>
						<SuggestionInput
							label="Employment"
							value={filters.employment}
							onChange={(value) => updateStringFilter("employment", value)}
							suggestions={suggestionsFor(manifest, "employment")}
							placeholder="full-time, contract"
						/>
						<SuggestionInput
							label="Remote"
							value={filters.remote}
							onChange={(value) => updateStringFilter("remote", value)}
							suggestions={suggestionsFor(manifest, "remote")}
							placeholder="remote"
						/>
						<SuggestionInput
							label="Salary min"
							value={filters.salaryMin}
							onChange={(value) => updateStringFilter("salaryMin", value)}
							placeholder="120000"
							type="number"
						/>
						<SuggestionInput
							label="Salary max"
							value={filters.salaryMax}
							onChange={(value) => updateStringFilter("salaryMax", value)}
							placeholder="180000"
							type="number"
						/>
						<SuggestionInput
							label="Posted after"
							value={filters.postedAfter}
							onChange={(value) => updateStringFilter("postedAfter", value)}
							type="date"
						/>
						<SuggestionInput
							label="Posted before"
							value={filters.postedBefore}
							onChange={(value) => updateStringFilter("postedBefore", value)}
							type="date"
						/>
					</div>
				</details>

				<div className="flex flex-col gap-3 border-t border-border/70 pt-3 md:flex-row md:items-start md:justify-between">
					<div className="min-w-0 flex-1 space-y-2">
						<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
							<Badge variant="outline">
								{formatCount(matchCount)}{" "}
								{searchActive ? "matches" : filters.includeAllIndexed ? "indexed jobs" : "open jobs"}
							</Badge>
							{activeFilterCount > 0 ? (
								<Badge variant="secondary">
									{activeFilterCount} active filters
								</Badge>
							) : (
								<Badge variant="muted">default view</Badge>
							)}
							<Badge variant="success">open jobs</Badge>
							{showHidden ? <Badge variant="warning">showing hidden</Badge> : null}
						</div>
						{chips.length > 0 ? (
							<div className="flex flex-wrap gap-1.5" aria-label="Active filters">
								{chips.map((chip) => (
									<button
										key={`${chip.key}-${chip.value}`}
										type="button"
										className="inline-flex max-w-full items-center gap-1 rounded-[var(--opps-radius-md)] border border-border/70 bg-background/75 px-2 py-1 text-xs text-muted-foreground hover:border-primary/45 hover:text-foreground"
										onClick={() => removeFilter(chip.key)}
										aria-label={`Remove ${chip.label} filter`}
									>
										<span className="font-semibold text-foreground">
											{chip.label}
										</span>
										<span className="max-w-44 truncate">{chip.value}</span>
										<X className="size-3" aria-hidden="true" />
									</button>
								))}
							</div>
						) : null}
					</div>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={onClear}
						disabled={activeFilterCount === 0}
					>
						<X className="size-3.5" />
						Clear filters
					</Button>
				</div>
				{savedSearches.length > 0 ? (
					<details className="rounded-[var(--opps-radius-md)] border border-border/70 bg-background/55">
						<summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-muted-foreground">
							<span className="inline-flex items-center gap-2">
								<BookmarkPlus className="size-3.5" />
								Saved searches
							</span>
							<ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
						</summary>
						<div className="grid gap-2 border-t border-border/70 p-3">
								{savedSearches.map(({ record, newMatches }) => (
									<div
									key={record.id}
									className="grid gap-2 rounded-[var(--opps-radius-md)] border border-border/70 bg-card/60 p-2 sm:grid-cols-[minmax(0,1fr)_auto]"
								>
									<button
										type="button"
										className="min-w-0 text-left"
										onClick={() => onRestoreSavedSearch(record)}
									>
										<span className="block truncate text-sm font-semibold text-foreground">
											{record.label}
										</span>
											<span className="mt-1 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
												<Badge
													variant={
														newMatches === null
															? "outline"
															: newMatches > 0
																? "info"
																: "muted"
													}
												>
													{newMatches === null
														? "syncing"
														: `${newMatches} new or changed`}
												</Badge>
												<Badge
													variant={record.baselineScope === "full" ? "success" : "outline"}
												>
													{record.baselineScope === "full"
														? "full baseline"
														: "page baseline"}
												</Badge>
												{record.lastReviewedAt ? (
												<Badge variant="outline">
													reviewed {record.lastReviewedAt.slice(0, 10)}
												</Badge>
											) : null}
										</span>
									</button>
									<div className="flex flex-wrap gap-1">
										<Button
											type="button"
											variant="outline"
											size="icon-xs"
											onClick={() => onRestoreSavedSearch(record)}
											aria-label={`Restore ${record.label}`}
										>
											<RotateCcw className="size-3" />
										</Button>
										<Button
											type="button"
											variant="outline"
											size="icon-xs"
											onClick={() => onReviewSavedSearch(record)}
											aria-label={`Mark ${record.label} reviewed`}
										>
											<CheckCheck className="size-3" />
										</Button>
										<Button
											type="button"
											variant="outline"
											size="icon-xs"
											onClick={() => onDuplicateSavedSearch(record)}
											aria-label={`Duplicate ${record.label}`}
										>
											<Copy className="size-3" />
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="icon-xs"
											onClick={() => onDeleteSavedSearch(record)}
											aria-label={`Delete ${record.label}`}
										>
											<Trash2 className="size-3" />
										</Button>
									</div>
								</div>
							))}
						</div>
					</details>
				) : null}
			</div>
		</TooltipProvider>
	);
}
