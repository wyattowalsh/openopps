import type { SearchRow } from "@/components/openopps-search/search-types";
import { compareText, J, normalize, text } from "@/components/openopps-search/search-utils";

/**
 * Shared job-row helpers for the jobs board and explorer filter engines.
 *
 * Intentional differences stay in each engine:
 * - Jobs board uses fuzzy/subsequence text matching (normalizeSuggestion, textFuzzyMatches).
 * - Explorer uses exact normalized term matching (matchesTerms on normalize(...)).
 */

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

export function latestObservedTimestamp(row: SearchRow) {
	const value = text(row[J.latestObserved]);
	if (!value) {
		return Number.NEGATIVE_INFINITY;
	}
	const parsed = Date.parse(value);
	return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export type LatestObservedTieBreak = "locale" | "compareText";

export function compareLatestObserved(
	left: SearchRow,
	right: SearchRow,
	tieBreak: LatestObservedTieBreak = "compareText",
) {
	const leftTime = latestObservedTimestamp(left);
	const rightTime = latestObservedTimestamp(right);
	if (leftTime !== rightTime) {
		return rightTime - leftTime;
	}
	const leftLabel = text(left[J.latestObserved]);
	const rightLabel = text(right[J.latestObserved]);
	if (tieBreak === "locale") {
		return rightLabel.localeCompare(leftLabel);
	}
	return compareText(rightLabel, leftLabel);
}

export function scoreQueryTermsInHaystack(haystack: string, queryTerms: string[]) {
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

export function jobBoardRelevanceHaystack(row: SearchRow) {
	return normalize(
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
}

export function relevanceScoreForJobRow(row: SearchRow, queryTerms: string[]) {
	return scoreQueryTermsInHaystack(jobBoardRelevanceHaystack(row), queryTerms);
}

export function jobFingerprint(row: SearchRow) {
	const hashFingerprint = [text(row[J.contentHash]), text(row[J.payloadHash])].filter(Boolean);
	if (hashFingerprint.length) {
		return hashFingerprint.join("|");
	}
	return [
		text(row[J.id]),
		text(row[J.latestObserved]),
		text(row[J.syncedAt]),
		text(row[J.title]),
		text(row[J.company]),
		text(row[J.descriptionSnippet]),
	]
		.filter(Boolean)
		.join("|");
}