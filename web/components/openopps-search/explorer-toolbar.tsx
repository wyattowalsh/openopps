import { Filter, Search, X } from "lucide-react";

import type { Entity, SearchManifest } from "@/components/openopps-search/search-types";
import {
	activeFilterCount,
	type ExplorerFilters,
	type ExplorerSortKey,
} from "@/components/openopps-search/explorer-filter-engine";
import { formatCount } from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

import {
	ExplorerFilterSelect,
	explorerFacetOptions,
} from "./explorer-shared";

const SORT_OPTIONS: Record<Entity, Array<{ value: ExplorerSortKey; label: string }>> = {
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

type ExplorerToolbarProps = {
	entity: Entity;
	filters: ExplorerFilters;
	manifest: SearchManifest | null;
	sortKey: ExplorerSortKey;
	matchCount: number;
	onFiltersChange: (updater: (current: ExplorerFilters) => ExplorerFilters) => void;
	onSortChange: (sortKey: ExplorerSortKey) => void;
	onClearFilters: () => void;
};

export function ExplorerToolbar({
	entity,
	filters,
	manifest,
	sortKey,
	matchCount,
	onFiltersChange,
	onSortChange,
	onClearFilters,
}: ExplorerToolbarProps) {
	const activeFilters = activeFilterCount(entity, filters);

	return (
		<div className="opps-toolbar mt-4 min-w-0 [&>*]:min-w-0">
			<div className="flex min-w-0 flex-wrap items-end gap-3 [&>*]:min-w-0">
				<label className="grid min-w-0 w-full basis-full gap-1.5 text-sm font-semibold sm:flex-1 sm:basis-[12rem]">
					<span className="flex min-w-0 items-center gap-2">
						<Search className="size-4 shrink-0" />
						Search
					</span>
					<input
						value={filters.query}
						onChange={(event) =>
							onFiltersChange((current) => ({
								...current,
								query: event.target.value,
							}))
						}
						placeholder="company, title, board, provider, route"
						className="opps-input opps-input--search w-full min-w-0 max-w-full"
						aria-label="Search dataset"
					/>
				</label>
				<ExplorerFilterSelect
					label="Sort"
					icon={Filter}
					value={sortKey}
					onChange={(value) => onSortChange(value as ExplorerSortKey)}
					options={SORT_OPTIONS[entity]}
					className="w-full basis-full sm:max-w-xs sm:flex-none"
				/>
			</div>

			<div className="grid min-w-0 gap-3 [&>*]:min-w-0 md:grid-cols-2 xl:grid-cols-4">
				<ExplorerFilterSelect
					label="Source"
					value={filters.source}
					onChange={(value) =>
						onFiltersChange((current) => ({ ...current, source: value }))
					}
					options={explorerFacetOptions(manifest?.facets.sources)}
				/>
				{entity !== "boards" ? (
					<ExplorerFilterSelect
						label="Provider"
						value={filters.provider}
						onChange={(value) =>
							onFiltersChange((current) => ({ ...current, provider: value }))
						}
						options={explorerFacetOptions(manifest?.facets.providerIds)}
					/>
				) : null}
				{entity === "jobs" ? (
					<>
						<ExplorerFilterSelect
							label="Job status"
							value={filters.jobStatus}
							onChange={(value) =>
								onFiltersChange((current) => ({
									...current,
									jobStatus: value,
								}))
							}
							options={explorerFacetOptions(manifest?.facets.jobStatuses)}
						/>
						<ExplorerFilterSelect
							label="Workplace"
							value={filters.workplace}
							onChange={(value) =>
								onFiltersChange((current) => ({
									...current,
									workplace: value,
								}))
							}
							options={explorerFacetOptions(manifest?.facets.workplaces)}
						/>
						<ExplorerFilterSelect
							label="Employment"
							value={filters.employment}
							onChange={(value) =>
								onFiltersChange((current) => ({
									...current,
									employment: value,
								}))
							}
							options={explorerFacetOptions(manifest?.facets.employmentTypes)}
						/>
						<label className="grid min-w-0 max-w-full gap-1.5 text-sm font-semibold">
							<span>Location</span>
							<input
								value={filters.location}
								onChange={(event) =>
									onFiltersChange((current) => ({
										...current,
										location: event.target.value,
									}))
								}
								placeholder="city, country, remote"
								className="opps-input w-full min-w-0 max-w-full"
								aria-label="Location"
							/>
						</label>
					</>
				) : null}
				{entity === "providers" ? (
					<>
						<ExplorerFilterSelect
							label="Support"
							value={filters.support}
							onChange={(value) =>
								onFiltersChange((current) => ({ ...current, support: value }))
							}
							options={explorerFacetOptions(manifest?.facets.supportLevels)}
						/>
						<ExplorerFilterSelect
							label="Route status"
							value={filters.routeStatus}
							onChange={(value) =>
								onFiltersChange((current) => ({
									...current,
									routeStatus: value,
								}))
							}
							options={explorerFacetOptions(manifest?.facets.routeStatuses)}
						/>
					</>
				) : null}
			</div>

			<div className="flex min-w-0 flex-col gap-3 border-t border-border/70 pt-3 md:flex-row md:items-center md:justify-between">
				<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<span className="font-semibold text-foreground">
						{formatCount(matchCount)} matches
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
				<Button type="button" variant="outline" size="sm" onClick={onClearFilters}>
					<X className="mr-2 size-3.5" />
					Clear filters
				</Button>
			</div>
		</div>
	);
}
