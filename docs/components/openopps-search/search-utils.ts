import type { Entity, SearchRow } from "./search-types";
import type { SearchSuggestion } from "./search-types";

export const SEARCH_VERSION = 4;

export const EXPECTED_PROVIDER_COLUMNS = [
	"id",
	"sourceKey",
	"boardKey",
	"providerId",
	"label",
	"supportLevel",
	"countHint",
	"boardUrl",
	"lastStatus",
];

export const EXPECTED_BOARD_COLUMNS = [
	"key",
	"sourceKey",
	"name",
	"domain",
	"websiteUrl",
	"staffCount",
	"numJobsHint",
];

export const JOB_COLUMN_INDICES = {
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
	sourceKeys: 19,
	descriptionSnippet: 20,
	skillTokens: 21,
	syncedAt: 22,
	firstSeenAt: 23,
	lastSeenAt: 24,
	closedAt: 25,
	contentHash: 26,
	payloadHash: 27,
} as const;

export const LEGACY_JOB_COLUMNS = [
	"id",
	"sourceKey",
	"boardKey",
	"providerId",
	"status",
	"title",
	"company",
	"department",
	"team",
	"workplaceType",
	"remote",
	"employmentType",
	"locations",
	"salaryMin",
	"salaryMax",
	"salaryCurrency",
	"postingUrl",
	"postedAt",
	"latestObservedAt",
	"sourceKeys",
	"descriptionSnippet",
	"skillTokens",
	"syncedAt",
];

export const EXPECTED_JOB_COLUMNS = [
	...LEGACY_JOB_COLUMNS,
	"firstSeenAt",
	"lastSeenAt",
	"closedAt",
	"contentHash",
	"payloadHash",
];

export const EXPECTED_COLUMNS = {
	providers: EXPECTED_PROVIDER_COLUMNS,
	boards: EXPECTED_BOARD_COLUMNS,
	jobs: EXPECTED_JOB_COLUMNS,
} as const;

export const J = JOB_COLUMN_INDICES;

export function expectedColumnsFor(entity: Entity, version: number) {
	if (entity === "jobs" && version === 3) {
		return LEGACY_JOB_COLUMNS;
	}
	return EXPECTED_COLUMNS[entity];
}

export function text(value: unknown) {
	if (value === null || value === undefined) {
		return "";
	}
	return String(value).trim();
}

export function normalize(value: string) {
	return value.toLowerCase().trim();
}

export function terms(value: string) {
	return normalize(value).split(/\s+/).filter(Boolean);
}

export function normalizeSuggestion(value: string) {
	return value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, " ")
		.trim();
}

export function rankSuggestions(
	suggestions: SearchSuggestion[] | undefined,
	query: string,
	limit = 12,
) {
	const normalizedQuery = normalizeSuggestion(query);
	const ranked = (suggestions ?? [])
		.map((suggestion) => ({
			suggestion,
			score: suggestionScore(suggestion, normalizedQuery),
		}))
		.filter((item) => item.score > 0)
		.sort(
			(left, right) =>
				right.score - left.score ||
				right.suggestion.count - left.suggestion.count ||
				compareText(left.suggestion.label, right.suggestion.label),
		);
	return ranked.slice(0, limit).map((item) => item.suggestion);
}

export function suggestionScore(
	suggestion: SearchSuggestion,
	normalizedQuery: string,
) {
	if (!normalizedQuery) {
		return 1 + Math.min(suggestion.count, 1000) / 1000;
	}
	const candidates = [
		suggestion.normalized,
		normalizeSuggestion(suggestion.value),
		normalizeSuggestion(suggestion.label),
		...(suggestion.aliases ?? []).map(normalizeSuggestion),
	].filter(Boolean);
	let score = 0;
	for (const candidate of candidates) {
		if (candidate === normalizedQuery) {
			score = Math.max(score, 100);
		} else if (candidate.startsWith(normalizedQuery)) {
			score = Math.max(score, 80);
		} else if (candidate.includes(normalizedQuery)) {
			score = Math.max(score, 60);
		} else if (subsequenceMatches(candidate, normalizedQuery)) {
			score = Math.max(score, 30);
		}
	}
	return score + Math.min(suggestion.count, 1000) / 1000;
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

export function compareText(left: string, right: string) {
	return left.localeCompare(right, undefined, {
		numeric: true,
		sensitivity: "base",
	});
}

export function formatCount(value: number | undefined) {
	if (value === undefined) {
		return "0";
	}
	return new Intl.NumberFormat("en-US").format(value);
}

export function formatDate(value: string) {
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

export function formatLocations(value: unknown) {
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

export function formatSalary(row: SearchRow) {
	const min = nullableNumber(row[J.salaryMin]);
	const max = nullableNumber(row[J.salaryMax]);
	const currency = text(row[J.currency]) || "USD";
	if (min === null && max === null) {
		return "";
	}
	const formatter = new Intl.NumberFormat("en-US", {
		style: "currency",
		currency,
		maximumFractionDigits: 0,
	});
	if (min !== null && max !== null) {
		return `${formatter.format(min)}-${formatter.format(max)}`;
	}
	if (min !== null) {
		return `${formatter.format(min)}+`;
	}
	if (max !== null) {
		return `Up to ${formatter.format(max)}`;
	}
	return "";
}

function nullableNumber(value: unknown) {
	if (value === null || value === undefined || value === "") {
		return null;
	}
	const numeric = Number(value);
	return Number.isFinite(numeric) ? numeric : null;
}

export function parseSourceKeys(value: unknown): string[] {
	const raw = text(value);
	if (!raw) {
		return [];
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		if (Array.isArray(parsed)) {
			return parsed.map((item) => text(item)).filter(Boolean);
		}
	} catch {
		return raw ? [raw] : [];
	}
	return [];
}

export function detailBucket(jobId: string) {
	let hash = 0;
	for (let index = 0; index < jobId.length; index += 1) {
		hash = (hash * 31 + jobId.charCodeAt(index)) >>> 0;
	}
	return (hash % 256).toString(16).padStart(2, "0");
}

export function detailPath(root: string, jobId: string) {
	return `${root}/${detailBucket(jobId)}.json`;
}

export type SearchLoadErrorCode =
	| "fetch_failed"
	| "unsupported_version"
	| "invalid_manifest"
	| "invalid_chunk"
	| "missing_entity_path";

export class SearchLoadError extends Error {
	readonly code: SearchLoadErrorCode;
	readonly path?: string;

	constructor(code: SearchLoadErrorCode, message: string, path?: string) {
		super(message);
		this.name = "SearchLoadError";
		this.code = code;
		this.path = path;
	}
}

export function formatLoadError(error: unknown) {
	if (error instanceof SearchLoadError) {
		switch (error.code) {
			case "unsupported_version":
				return "The committed search snapshot uses an unsupported index version. Regenerate with pnpm data:generate:search.";
			case "invalid_manifest":
				return "The search manifest is missing required entity columns. Regenerate the docs search snapshot.";
			case "invalid_chunk":
				return "A search index chunk failed validation. Regenerate the docs search snapshot.";
			case "missing_entity_path":
				return "The search manifest is missing an entity path. Regenerate the docs search snapshot.";
			case "fetch_failed":
			default:
				return error.message;
		}
	}
	if (error instanceof Error) {
		return error.message;
	}
	return "Unable to load the OpenOpps search index.";
}
