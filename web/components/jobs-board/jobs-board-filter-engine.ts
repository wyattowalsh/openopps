// Board filters use fuzzy matching; explorer uses exact normalized terms (see search-job-core).
import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	compareLatestObserved,
	postedAtInRange,
	relevanceScoreForJobRow,
	salaryOverlaps,
} from "@/lib/search-job-core";
import {
	J,
	normalize,
	normalizeSuggestion,
	parseSourceKeys,
	text,
} from "@/components/openopps-search/search-utils";

export type JobBoardFilters = {
	query: string;
	wide: boolean;
	includeAllIndexed: boolean;
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

export type JobSortKey = "latest" | "relevance";

export const DEFAULT_JOB_BOARD_FILTERS: JobBoardFilters = {
	query: "",
	wide: false,
	includeAllIndexed: false,
	source: "",
	provider: "",
	location: "",
	department: "",
	team: "",
	workplace: "",
	remote: "",
	employment: "",
	skill: "",
	salaryMin: "",
	salaryMax: "",
	postedAfter: "",
	postedBefore: "",
};

function textContains(value: string | null | undefined, needle: string) {
	return normalize(value ?? "").includes(normalize(needle));
}

function textEquals(value: string | null | undefined, needle: string) {
	return normalize(value ?? "") === normalize(needle);
}

function subsequenceMatches(value: string, query: string) {
	if (!query) {
		return true;
	}
	let queryIndex = 0;
	for (const char of value) {
		if (char === query[queryIndex]) {
			queryIndex += 1;
			if (queryIndex === query.length) {
				return true;
			}
		}
	}
	return false;
}

function textFuzzyMatches(value: string | null | undefined, needle: string) {
	if (!needle) {
		return true;
	}
	const normalizedValue = normalizeSuggestion(value ?? "");
	const normalizedNeedle = normalizeSuggestion(needle);
	if (!normalizedNeedle) {
		return true;
	}
	return (
		normalizedValue === normalizedNeedle ||
		normalizedValue.includes(normalizedNeedle) ||
		subsequenceMatches(normalizedValue, normalizedNeedle)
	);
}

export { postedAtInRange, salaryOverlaps };

export function skillMatches(row: SearchRow, needle: string) {
	if (!needle) {
		return true;
	}
	return textFuzzyMatches(text(row[J.skillTokens]), needle);
}

export function queryMatches(row: SearchRow, query: string, wide: boolean) {
	if (!query) {
		return true;
	}
	const fields = [text(row[J.title]), text(row[J.company]), text(row[J.descriptionSnippet])];
	if (wide) {
		fields.push(
			text(row[J.department]),
			text(row[J.team]),
			formatLocationsForQuery(row[J.locations]),
			text(row[J.provider]),
			text(row[J.board]),
			text(row[J.source]),
		);
	}
	return fields.some((field) => textContains(field, query));
}

function formatLocationsForQuery(value: unknown) {
	const raw = text(value);
	if (!raw) {
		return "";
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		if (Array.isArray(parsed)) {
			return parsed.map((item) => text(item)).join(" ");
		}
	} catch {
		return raw;
	}
	return raw;
}

export function sourceKeyMatches(row: SearchRow, sourceKey: string) {
	if (!sourceKey) {
		return true;
	}
	const keys = parseSourceKeys(row[J.sourceKeys]);
	if (keys.length > 0) {
		return (
			keys.includes(sourceKey) ||
			keys.some((key) => textFuzzyMatches(key, sourceKey))
		);
	}
	return textFuzzyMatches(text(row[J.source]), sourceKey);
}

export function locationMatches(row: SearchRow, location: string) {
	if (!location) {
		return true;
	}
	return textFuzzyMatches(formatLocationsForQuery(row[J.locations]), location);
}

export function jobMatchesFilters(row: SearchRow, filters: JobBoardFilters) {
	if (!filters.includeAllIndexed && text(row[J.status]) !== "open") {
		return false;
	}
	if (!sourceKeyMatches(row, filters.source)) {
		return false;
	}
	if (filters.provider && !textFuzzyMatches(text(row[J.provider]), filters.provider)) {
		return false;
	}
	if (!locationMatches(row, filters.location)) {
		return false;
	}
	if (
		filters.department &&
		!textFuzzyMatches(text(row[J.department]), filters.department)
	) {
		return false;
	}
	if (filters.team && !textFuzzyMatches(text(row[J.team]), filters.team)) {
		return false;
	}
	if (
		filters.workplace &&
		!textFuzzyMatches(text(row[J.workplace]), filters.workplace) &&
		!textFuzzyMatches(text(row[J.remote]), filters.workplace)
	) {
		return false;
	}
	if (
		filters.remote &&
		!textEquals(text(row[J.remote]), filters.remote) &&
		!textFuzzyMatches(text(row[J.remote]), filters.remote)
	) {
		return false;
	}
	if (filters.employment && !textFuzzyMatches(text(row[J.type]), filters.employment)) {
		return false;
	}
	const salaryMin = filters.salaryMin ? Number(filters.salaryMin) : null;
	const salaryMax = filters.salaryMax ? Number(filters.salaryMax) : null;
	if (
		!salaryOverlaps(
			row,
			Number.isFinite(salaryMin) ? salaryMin : null,
			Number.isFinite(salaryMax) ? salaryMax : null,
		)
	) {
		return false;
	}
	if (!skillMatches(row, filters.skill)) {
		return false;
	}
	if (!queryMatches(row, filters.query, filters.wide)) {
		return false;
	}
	if (!postedAtInRange(row, filters.postedAfter, filters.postedBefore)) {
		return false;
	}
	return true;
}

export function relevanceScore(row: SearchRow, queryTerms: string[]) {
	return relevanceScoreForJobRow(row, queryTerms);
}

export function filterAndSortJobs(
	rows: SearchRow[],
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) {
	const queryTerms = normalize(filters.query).split(/\s+/).filter(Boolean);
	const filtered = rows.filter((row) => jobMatchesFilters(row, filters));
	if (sortKey === "relevance" && queryTerms.length > 0) {
		// Precompute scores once (O(n)); avoid scoring inside the comparator.
		const scored = filtered.map((row) => ({
			row,
			score: relevanceScore(row, queryTerms),
			observed: text(row[J.latestObserved]),
		}));
		scored.sort(
			(left, right) =>
				right.score - left.score ||
				right.observed.localeCompare(left.observed) ||
				compareLatestObserved(left.row, right.row, "locale"),
		);
		return scored.map((entry) => entry.row);
	}
	return [...filtered].sort((left, right) =>
		compareLatestObserved(left, right, "locale"),
	);
}
