"use client";

import { useCallback, useDeferredValue, useMemo } from "react";
import {
	debounce,
	parseAsInteger,
	parseAsString,
	useQueryStates,
} from "nuqs";

import type { Entity } from "@/components/openopps-search/search-types";
import {
	DEFAULT_EXPLORER_FILTERS,
	DEFAULT_EXPLORER_SORT,
	PAGE_SIZE,
	type ExplorerFilters,
	type ExplorerSortKey,
} from "@/components/openopps-search/explorer-filter-engine";

/** Shareable URL keys aligned with the jobs board (`q`, facet keys) plus explorer-specific `entity`, `sort`, and `page`. */
export const explorerQueryParsers = {
	entity: parseAsString.withDefault("jobs"),
	q: parseAsString.withDefault(""),
	source: parseAsString.withDefault(""),
	provider: parseAsString.withDefault(""),
	jobStatus: parseAsString.withDefault("open"),
	support: parseAsString.withDefault(""),
	routeStatus: parseAsString.withDefault(""),
	workplace: parseAsString.withDefault(""),
	employment: parseAsString.withDefault(""),
	location: parseAsString.withDefault(""),
	sort: parseAsString.withDefault(""),
	page: parseAsInteger.withDefault(1),
} as const;

export type ExplorerQueryState = {
	entity: string;
	q: string;
	source: string;
	provider: string;
	jobStatus: string;
	support: string;
	routeStatus: string;
	workplace: string;
	employment: string;
	location: string;
	sort: string;
	page: number;
};

const ENTITIES = new Set<Entity>(["jobs", "boards", "providers"]);

export function parseExplorerEntity(value: string): Entity {
	if (ENTITIES.has(value as Entity)) {
		return value as Entity;
	}
	return "jobs";
}

export function filtersFromExplorerQuery(
	state: ExplorerQueryState,
): ExplorerFilters {
	return {
		query: state.q,
		source: state.source,
		provider: state.provider,
		jobStatus: state.jobStatus,
		support: state.support,
		routeStatus: state.routeStatus,
		workplace: state.workplace,
		employment: state.employment,
		location: state.location,
	};
}

export function resolveExplorerSortKey(
	entity: Entity,
	sort: string,
): ExplorerSortKey {
	const options = SORT_KEYS_BY_ENTITY[entity];
	if (options.includes(sort as ExplorerSortKey)) {
		return sort as ExplorerSortKey;
	}
	return DEFAULT_EXPLORER_SORT[entity];
}

export function visibleLimitFromPage(page: number) {
	return Math.max(1, page) * PAGE_SIZE;
}

export function pageFromVisibleLimit(visibleLimit: number) {
	return Math.max(1, Math.ceil(visibleLimit / PAGE_SIZE));
}

const SORT_KEYS_BY_ENTITY: Record<Entity, ExplorerSortKey[]> = {
	jobs: ["latest", "relevance", "title", "company", "provider", "status"],
	boards: ["name", "source"],
	providers: ["provider", "support", "status", "source"],
};

export const EXPLORER_FILTER_DEBOUNCE_MS = 200;

export const explorerFilterQueryOptions = {
	history: "replace" as const,
	shallow: true,
	clearOnDefault: true,
	limitUrlUpdates: debounce(EXPLORER_FILTER_DEBOUNCE_MS),
};

export function useExplorerFilterState() {
	const [state, setState] = useQueryStates(
		explorerQueryParsers,
		explorerFilterQueryOptions,
	);

	const entity = useMemo(
		() => parseExplorerEntity(state.entity),
		[state.entity],
	);
	const filters = useMemo(
		() => filtersFromExplorerQuery(state),
		[state],
	);
	const sortKey = useMemo(
		() => resolveExplorerSortKey(entity, state.sort),
		[entity, state.sort],
	);
	const visibleLimit = useMemo(
		() => visibleLimitFromPage(state.page),
		[state.page],
	);
	const deferredFilters = useDeferredValue(filters);

	const setEntity = useCallback(
		(nextEntity: Entity) => {
			setState({
				entity: nextEntity,
				sort: DEFAULT_EXPLORER_SORT[nextEntity],
				page: 1,
			});
		},
		[setState],
	);

	const setFilters = useCallback(
		(updater: (current: ExplorerFilters) => ExplorerFilters) => {
			setState((current) => {
				const next = updater(filtersFromExplorerQuery(current));
				return {
					q: next.query,
					source: next.source,
					provider: next.provider,
					jobStatus: next.jobStatus,
					support: next.support,
					routeStatus: next.routeStatus,
					workplace: next.workplace,
					employment: next.employment,
					location: next.location,
					page: 1,
				};
			});
		},
		[setState],
	);

	const setSortKey = useCallback(
		(nextSort: ExplorerSortKey) => {
			setState({ sort: nextSort, page: 1 });
		},
		[setState],
	);

	const setVisibleLimit = useCallback(
		(nextLimit: number) => {
			setState({ page: pageFromVisibleLimit(nextLimit) });
		},
		[setState],
	);

	const clearFilters = useCallback(() => {
		setState({
			q: DEFAULT_EXPLORER_FILTERS.query,
			source: DEFAULT_EXPLORER_FILTERS.source,
			provider: DEFAULT_EXPLORER_FILTERS.provider,
			jobStatus: DEFAULT_EXPLORER_FILTERS.jobStatus,
			support: DEFAULT_EXPLORER_FILTERS.support,
			routeStatus: DEFAULT_EXPLORER_FILTERS.routeStatus,
			workplace: DEFAULT_EXPLORER_FILTERS.workplace,
			employment: DEFAULT_EXPLORER_FILTERS.employment,
			location: DEFAULT_EXPLORER_FILTERS.location,
			page: 1,
		});
	}, [setState]);

	const resetPage = useCallback(() => {
		setState({ page: 1 });
	}, [setState]);

	return {
		entity,
		filters,
		deferredFilters,
		sortKey,
		visibleLimit,
		setEntity,
		setFilters,
		setSortKey,
		setVisibleLimit,
		clearFilters,
		resetPage,
	};
}
