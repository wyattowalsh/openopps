import type { SearchRow } from "./search-types";

export const SEARCH_VERSION = 3;

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
} as const;

export const EXPECTED_JOB_COLUMNS = [
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

export const EXPECTED_COLUMNS = {
	providers: EXPECTED_PROVIDER_COLUMNS,
	boards: EXPECTED_BOARD_COLUMNS,
	jobs: EXPECTED_JOB_COLUMNS,
} as const;

export const J = JOB_COLUMN_INDICES;

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
