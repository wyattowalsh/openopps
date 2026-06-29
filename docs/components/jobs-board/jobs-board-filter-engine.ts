import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	J,
	normalize,
	parseSourceKeys,
	text,
} from "@/components/openopps-search/search-utils";

export type JobBoardFilters = {
	query: string;
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

export type JobSortKey = "latest" | "relevance";

export const DEFAULT_JOB_BOARD_FILTERS: JobBoardFilters = {
	query: "",
	wide: false,
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

function dateKey(value: string | null | undefined) {
	if (!value) {
		return null;
	}
	const match = value.match(/^([1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9])/);
	return match ? match[1] : null;
}

function salaryValue(value: unknown): number | null {
	if (value === null || value === undefined || value === "") {
		return null;
	}
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function latestTimestampValue(row: SearchRow) {
	const value = text(row[J.latestObserved]);
	if (!value) {
		return Number.NEGATIVE_INFINITY;
	}
	const parsed = Date.parse(value);
	return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function compareLatestObserved(left: SearchRow, right: SearchRow) {
	const leftTime = latestTimestampValue(left);
	const rightTime = latestTimestampValue(right);
	if (leftTime !== rightTime) {
		return rightTime - leftTime;
	}
	return text(right[J.latestObserved]).localeCompare(text(left[J.latestObserved]));
}

export function salaryOverlaps(
	row: SearchRow,
	requestedMin: number | null,
	requestedMax: number | null,
) {
	if (requestedMin === null && requestedMax === null) {
		return true;
	}
	const jobMin = salaryValue(row[J.salaryMin]);
	const jobMax = salaryValue(row[J.salaryMax]);
	if (jobMin === null && jobMax === null) {
		return false;
	}
	if (requestedMin !== null) {
		const candidateMax = jobMax ?? jobMin;
		if (candidateMax === null || candidateMax < requestedMin) {
			return false;
		}
	}
	if (requestedMax !== null) {
		const candidateMin = jobMin ?? jobMax;
		if (candidateMin === null || candidateMin > requestedMax) {
			return false;
		}
	}
	return true;
}

export function skillMatches(row: SearchRow, needle: string) {
	if (!needle) {
		return true;
	}
	return textContains(text(row[J.skillTokens]), needle);
}

export function postedAtInRange(
	row: SearchRow,
	postedAfter: string,
	postedBefore: string,
) {
	if (!postedAfter && !postedBefore) {
		return true;
	}
	const postedKey = dateKey(text(row[J.posted]));
	if (!postedKey) {
		return false;
	}
	const afterKey = dateKey(postedAfter);
	const beforeKey = dateKey(postedBefore);
	if (afterKey && postedKey < afterKey) {
		return false;
	}
	if (beforeKey && postedKey > beforeKey) {
		return false;
	}
	return true;
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
		return keys.includes(sourceKey);
	}
	return text(row[J.source]) === sourceKey;
}

export function locationMatches(row: SearchRow, location: string) {
	if (!location) {
		return true;
	}
	return textContains(formatLocationsForQuery(row[J.locations]), location);
}

export function jobMatchesFilters(row: SearchRow, filters: JobBoardFilters) {
	if (text(row[J.status]) !== "open") {
		return false;
	}
	if (!sourceKeyMatches(row, filters.source)) {
		return false;
	}
	if (filters.provider && text(row[J.provider]) !== filters.provider) {
		return false;
	}
	if (!locationMatches(row, filters.location)) {
		return false;
	}
	if (filters.department && !textContains(text(row[J.department]), filters.department)) {
		return false;
	}
	if (filters.team && !textContains(text(row[J.team]), filters.team)) {
		return false;
	}
	if (
		filters.workplace &&
		!textContains(text(row[J.workplace]), filters.workplace) &&
		!textContains(text(row[J.remote]), filters.workplace)
	) {
		return false;
	}
	if (filters.remote && !textEquals(text(row[J.remote]), filters.remote)) {
		return false;
	}
	if (filters.employment && !textContains(text(row[J.type]), filters.employment)) {
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
	const haystack = normalize(
		[
			row[J.title],
			row[J.company],
			row[J.descriptionSnippet],
			row[J.department],
			row[J.team],
		]
			.map((value) => text(value))
			.join(" "),
	);
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

export function filterAndSortJobs(
	rows: SearchRow[],
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) {
	const queryTerms = normalize(filters.query).split(/\s+/).filter(Boolean);
	const filtered = rows.filter((row) => jobMatchesFilters(row, filters));
	return [...filtered].sort((left, right) => {
		if (sortKey === "relevance" && queryTerms.length > 0) {
			return (
				relevanceScore(right, queryTerms) - relevanceScore(left, queryTerms) ||
				compareLatestObserved(left, right)
			);
		}
		return compareLatestObserved(left, right);
	});
}
