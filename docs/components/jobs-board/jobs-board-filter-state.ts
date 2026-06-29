"use client";

import { useCallback, useDeferredValue, useMemo } from "react";
import {
	debounce,
	parseAsBoolean,
	parseAsString,
	useQueryState,
	useQueryStates,
} from "nuqs";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";

export const jobBoardQueryParsers = {
	q: parseAsString.withDefault(""),
	wide: parseAsBoolean.withDefault(false),
	source: parseAsString.withDefault(""),
	provider: parseAsString.withDefault(""),
	location: parseAsString.withDefault(""),
	department: parseAsString.withDefault(""),
	team: parseAsString.withDefault(""),
	workplace: parseAsString.withDefault(""),
	remote: parseAsString.withDefault(""),
	employment: parseAsString.withDefault(""),
	skill: parseAsString.withDefault(""),
	salaryMin: parseAsString.withDefault(""),
	salaryMax: parseAsString.withDefault(""),
	postedAfter: parseAsString.withDefault(""),
	postedBefore: parseAsString.withDefault(""),
} as const;

export type JobBoardQueryState = {
	q: string;
	wide: boolean;
	source: string;
	provider: string;
	location: string;
	department: string;
	team: string;
	workplace: string;
	remote: string;
	employment: string;
	skill: string;
	salaryMin: string;
	salaryMax: string;
	postedAfter: string;
	postedBefore: string;
};

export function filtersFromQueryState(
	state: JobBoardQueryState,
): JobBoardFilters {
	return {
		query: state.q,
		wide: state.wide,
		source: state.source,
		provider: state.provider,
		location: state.location,
		department: state.department,
		team: state.team,
		workplace: state.workplace,
		remote: state.remote,
		employment: state.employment,
		skill: state.skill,
		salaryMin: state.salaryMin,
		salaryMax: state.salaryMax,
		postedAfter: state.postedAfter,
		postedBefore: state.postedBefore,
	};
}

export function countActiveFilters(filters: JobBoardFilters) {
	let count = 0;
	if (filters.query) count += 1;
	if (filters.wide) count += 1;
	if (filters.source) count += 1;
	if (filters.provider) count += 1;
	if (filters.location) count += 1;
	if (filters.department) count += 1;
	if (filters.team) count += 1;
	if (filters.workplace) count += 1;
	if (filters.remote) count += 1;
	if (filters.employment) count += 1;
	if (filters.skill) count += 1;
	if (filters.salaryMin) count += 1;
	if (filters.salaryMax) count += 1;
	if (filters.postedAfter) count += 1;
	if (filters.postedBefore) count += 1;
	return count;
}

export const JOB_FILTER_DEBOUNCE_MS = 200;

export const filterQueryOptions = {
	history: "replace" as const,
	shallow: true,
	clearOnDefault: true,
	limitUrlUpdates: debounce(JOB_FILTER_DEBOUNCE_MS),
};

export const selectedJobQueryOptions = {
	history: "push" as const,
	shallow: true,
	clearOnDefault: true,
};

export function useJobBoardFilterState() {
	const [state, setState] = useQueryStates(
		jobBoardQueryParsers,
		filterQueryOptions,
	);
	const [selectedJobState, setSelectedJobState] = useQueryState(
		"job",
		parseAsString.withDefault("").withOptions(selectedJobQueryOptions),
	);

	const filters = useMemo(() => filtersFromQueryState(state), [state]);
	const selectedJobId = selectedJobState || null;
	const setSelectedJobId = useCallback(
		(jobId: string | null) => setSelectedJobState(jobId ?? ""),
		[setSelectedJobState],
	);
	const deferredFilters = useDeferredValue(filters);

	const setFilters = useCallback(
		(next: Partial<JobBoardFilters>) => {
			setState((current) => ({
				q: next.query ?? current.q,
				wide: next.wide ?? current.wide,
				source: next.source ?? current.source,
				provider: next.provider ?? current.provider,
				location: next.location ?? current.location,
				department: next.department ?? current.department,
				team: next.team ?? current.team,
				workplace: next.workplace ?? current.workplace,
				remote: next.remote ?? current.remote,
				employment: next.employment ?? current.employment,
				skill: next.skill ?? current.skill,
				salaryMin: next.salaryMin ?? current.salaryMin,
				salaryMax: next.salaryMax ?? current.salaryMax,
				postedAfter: next.postedAfter ?? current.postedAfter,
				postedBefore: next.postedBefore ?? current.postedBefore,
			}));
		},
		[setState],
	);

	const clearFilters = useCallback(() => {
		setState({
			q: DEFAULT_JOB_BOARD_FILTERS.query,
			wide: DEFAULT_JOB_BOARD_FILTERS.wide,
			source: DEFAULT_JOB_BOARD_FILTERS.source,
			provider: DEFAULT_JOB_BOARD_FILTERS.provider,
			location: DEFAULT_JOB_BOARD_FILTERS.location,
			department: DEFAULT_JOB_BOARD_FILTERS.department,
			team: DEFAULT_JOB_BOARD_FILTERS.team,
			workplace: DEFAULT_JOB_BOARD_FILTERS.workplace,
			remote: DEFAULT_JOB_BOARD_FILTERS.remote,
			employment: DEFAULT_JOB_BOARD_FILTERS.employment,
			skill: DEFAULT_JOB_BOARD_FILTERS.skill,
			salaryMin: DEFAULT_JOB_BOARD_FILTERS.salaryMin,
			salaryMax: DEFAULT_JOB_BOARD_FILTERS.salaryMax,
			postedAfter: DEFAULT_JOB_BOARD_FILTERS.postedAfter,
			postedBefore: DEFAULT_JOB_BOARD_FILTERS.postedBefore,
		});
	}, [setState]);

	return {
		filters,
		deferredFilters,
		selectedJobId,
		setFilters,
		setSelectedJobId,
		clearFilters,
		activeFilterCount: countActiveFilters(filters),
	};
}
