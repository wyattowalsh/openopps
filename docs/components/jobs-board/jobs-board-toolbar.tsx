"use client";

import { Filter, Search, X } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import type { JobBoardFilters } from "@/components/jobs-board/jobs-board-filter-engine";
import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatCount } from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

type JobsBoardToolbarProps = {
	filters: JobBoardFilters;
	manifest: SearchManifest | null;
	matchCount: number;
	activeFilterCount: number;
	onChange: (next: Partial<JobBoardFilters>) => void;
	onClear: () => void;
};

function facetOptions(values: string[] | undefined) {
	return [
		{ value: "", label: "Any" },
		...(values ?? []).map((value) => ({ value, label: value })),
	];
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

function FilterInput({
	label,
	value,
	onChange,
	placeholder,
	type = "text",
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	type?: string;
}) {
	return (
		<label className="grid gap-1.5 text-sm font-semibold">
			<span>{label}</span>
			<input
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				className="opps-input"
				aria-label={label}
			/>
		</label>
	);
}

export function JobsBoardToolbar({
	filters,
	manifest,
	matchCount,
	activeFilterCount,
	onChange,
	onClear,
}: JobsBoardToolbarProps) {
	return (
		<div className="opps-toolbar">
			<div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_auto]">
				<label className="grid gap-1.5 text-sm font-semibold">
					<span className="flex items-center gap-2">
						<Search className="size-4" />
						Search
						</span>
						<input
							value={filters.query}
							onChange={(event) => onChange({ query: event.target.value })}
							placeholder="title, company, description"
						className="opps-input opps-input--search"
						aria-label="Search jobs"
					/>
				</label>
				<label className="flex items-end gap-2 pb-1 text-sm font-semibold">
					<input
						type="checkbox"
						checked={filters.wide}
						onChange={(event) => onChange({ wide: event.target.checked })}
						className="size-4 rounded border-border"
					/>
					<span>Wide search (dept, team, locations, provider)</span>
				</label>
			</div>

			<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
				<FilterSelect
					label="Source"
					value={filters.source}
					onChange={(value) => onChange({ source: value })}
					options={facetOptions(manifest?.facets.sources)}
				/>
				<FilterSelect
					label="Provider"
					value={filters.provider}
					onChange={(value) => onChange({ provider: value })}
					options={facetOptions(manifest?.facets.providerIds)}
				/>
				<FilterSelect
					label="Workplace"
					value={filters.workplace}
					onChange={(value) => onChange({ workplace: value })}
					options={facetOptions(manifest?.facets.workplaces)}
				/>
				<FilterSelect
					label="Employment"
					value={filters.employment}
					onChange={(value) => onChange({ employment: value })}
					options={facetOptions(manifest?.facets.employmentTypes)}
				/>
				<FilterInput
					label="Location"
					value={filters.location}
					onChange={(value) => onChange({ location: value })}
					placeholder="city, country, remote"
				/>
				<FilterInput
					label="Department"
					value={filters.department}
					onChange={(value) => onChange({ department: value })}
					placeholder="engineering, sales"
				/>
				<FilterInput
					label="Team"
					value={filters.team}
					onChange={(value) => onChange({ team: value })}
					placeholder="platform, growth"
				/>
				<FilterInput
					label="Remote"
					value={filters.remote}
					onChange={(value) => onChange({ remote: value })}
					placeholder="remote, hybrid"
				/>
				<FilterInput
					label="Skill"
					value={filters.skill}
					onChange={(value) => onChange({ skill: value })}
					placeholder="python, kubernetes"
				/>
				<FilterInput
					label="Salary min"
					value={filters.salaryMin}
					onChange={(value) => onChange({ salaryMin: value })}
					placeholder="120000"
					type="number"
				/>
				<FilterInput
					label="Salary max"
					value={filters.salaryMax}
					onChange={(value) => onChange({ salaryMax: value })}
					placeholder="180000"
					type="number"
				/>
				<FilterInput
					label="Posted after"
					value={filters.postedAfter}
					onChange={(value) => onChange({ postedAfter: value })}
					type="date"
				/>
				<FilterInput
					label="Posted before"
					value={filters.postedBefore}
					onChange={(value) => onChange({ postedBefore: value })}
					type="date"
				/>
			</div>

			<div className="flex flex-col gap-3 border-t border-border/70 pt-3 md:flex-row md:items-center md:justify-between">
				<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<Filter className="size-4" />
					<span className="font-semibold text-foreground">
						{formatCount(matchCount)} matches
					</span>
					{activeFilterCount > 0 ? (
						<span>{activeFilterCount} active filters</span>
					) : (
						<span>default view</span>
					)}
					<span className="openopps-status-chip" data-tone="jobs">
						open
					</span>
				</div>
				<Button type="button" variant="outline" size="sm" onClick={onClear}>
					<X className="mr-2 size-3.5" />
					Clear filters
				</Button>
			</div>
		</div>
	);
}
