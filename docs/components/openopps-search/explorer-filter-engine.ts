import type { Entity, SearchRow } from "./search-types";
import {
	J,
	compareText,
	normalize,
	parseSourceKeys,
	terms,
	text,
} from "./search-utils";

export type ExplorerFilters = {
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

export type ExplorerSortKey =
	| "latest"
	| "relevance"
	| "title"
	| "company"
	| "name"
	| "provider"
	| "source"
	| "support"
	| "status";

export const PAGE_SIZE = 50;

export const P = {
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

export const B = {
	key: 0,
	source: 1,
	name: 2,
	domain: 3,
	url: 4,
	staff: 5,
	hint: 6,
} as const;

export { J, terms };

export const DEFAULT_EXPLORER_SORT: Record<Entity, ExplorerSortKey> = {
	jobs: "latest",
	boards: "name",
	providers: "provider",
};

export const DEFAULT_EXPLORER_FILTERS: ExplorerFilters = {
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

export function matchesRow(
	entity: Entity,
	row: SearchRow,
	filters: ExplorerFilters,
	queryTerms: string[],
	locationTerms: string[],
) {
	if (queryTerms.length > 0 && !matchesTerms(searchText(entity, row), queryTerms)) {
		return false;
	}
	if (!sourceMatches(entity, row, filters.source)) {
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

export function sortRows(
	entity: Entity,
	rows: SearchRow[],
	sortKey: ExplorerSortKey,
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

export function sourceMatches(entity: Entity, row: SearchRow, source: string) {
	if (!source) {
		return true;
	}
	if (entity === "jobs") {
		const keys = parseSourceKeys(row[J.sourceKeys]);
		if (keys.length > 0) {
			return keys.includes(source);
		}
		return text(row[J.source]) === source;
	}
	if (entity === "boards") {
		return text(row[B.source]) === source;
	}
	return text(row[P.source]) === source;
}

export function activeFilterCount(entity: Entity, filters: ExplorerFilters) {
	let count = Number(Boolean(filters.query)) + Number(Boolean(filters.source));
	if (entity !== "boards") {
		count += Number(Boolean(filters.provider));
	}
	if (entity === "jobs") {
		count +=
			Number(filters.jobStatus !== DEFAULT_EXPLORER_FILTERS.jobStatus) +
			Number(Boolean(filters.workplace)) +
			Number(Boolean(filters.employment)) +
			Number(Boolean(filters.location));
	}
	if (entity === "providers") {
		count += Number(Boolean(filters.support)) + Number(Boolean(filters.routeStatus));
	}
	return count;
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
				row[J.sourceKeys],
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

function matchesTerms(value: string, queryTerms: string[]) {
	return queryTerms.every((term) => value.includes(term));
}

function providerValue(entity: Entity, row: SearchRow) {
	if (entity === "jobs") {
		return text(row[J.provider]);
	}
	return text(row[P.provider]);
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
