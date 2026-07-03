import type { JobDetail } from "@/components/openopps-search/search-types";
import { cleanText, safeJobExternalUrl } from "@/lib/job-url";
import { siteUrl } from "@/lib/shared";

export { cleanText, safeJobExternalUrl } from "@/lib/job-url";

export function serializeJsonLdScript(value: unknown) {
	return JSON.stringify(value)
		.replace(/</g, "\\u003c")
		.replace(/>/g, "\\u003e")
		.replace(/&/g, "\\u0026")
		.replace(/\u2028/g, "\\u2028")
		.replace(/\u2029/g, "\\u2029");
}

export function canonicalJobUrl(jobId: string) {
	return `${siteUrl}/jobs/${encodeURIComponent(jobId)}`;
}

export function jobBoardDeepLink(jobId: string) {
	return `/?job=${encodeURIComponent(jobId)}`;
}

export function formatJobDetailTitle(detail: JobDetail) {
	const title = cleanText(detail.title) || "Untitled role";
	const company = cleanText(detail.company);
	return company ? `${title} at ${company}` : title;
}

export function jobDescriptionText(detail: JobDetail, maxLength = 240) {
	const raw =
		jobDetailDescriptionText(detail) ||
		"Open public job posting from the OpenOpps static snapshot.";
	if (raw.length <= maxLength) {
		return raw;
	}
	return `${raw.slice(0, maxLength - 1).trim()}...`;
}

export function jobDetailDescriptionText(detail: JobDetail) {
	return (
		cleanText(stripHtml(detail.description ?? "")) ||
		cleanText(stripHtml(detail.descriptionHtml ?? ""))
	);
}

export function primaryJobExternalUrl(detail: JobDetail) {
	return safeJobExternalUrl(detail.postingUrl) ?? safeJobExternalUrl(detail.applyUrl);
}

export function isIndexableJobDetail(detail: JobDetail) {
	const status = cleanText(detail.status).toLowerCase();
	const hasOpenStatus = !status || status === "open";
	const hasCoreContent = Boolean(
		cleanText(detail.title) &&
			cleanText(detail.company) &&
			jobDetailDescriptionText(detail),
	);
	const hasDate = Boolean(
		dateOrUndefined(detail.postedAt ?? detail.firstSeenAt ?? detail.versionCreatedAt),
	);
	return Boolean(hasOpenStatus && hasCoreContent && hasDate && primaryJobExternalUrl(detail));
}

export function shouldEmitJobPostingJsonLd(detail: JobDetail) {
	if (!jobPostingJsonLdEnabled()) {
		return false;
	}
	return isIndexableJobDetail(detail);
}

export function jobPostingJsonLd(detail: JobDetail) {
	if (!shouldEmitJobPostingJsonLd(detail)) {
		return null;
	}
	const title = cleanText(detail.title);
	const company = cleanText(detail.company);
	const postingUrl = primaryJobExternalUrl(detail);
	const locations = (detail.locations ?? []).map(cleanText).filter(Boolean);
	return {
		"@context": "https://schema.org",
		"@type": "JobPosting",
		title,
		description: jobDetailDescriptionText(detail),
		datePosted: dateOrUndefined(
			detail.postedAt ?? detail.firstSeenAt ?? detail.versionCreatedAt,
		)?.toISOString(),
		validThrough: dateOrUndefined(detail.closedAt)?.toISOString(),
		employmentType: cleanText(detail.employmentType) || undefined,
		hiringOrganization: {
			"@type": "Organization",
			name: company,
		},
		identifier: {
			"@type": "PropertyValue",
			name: company,
			value: detail.id,
		},
		jobLocation:
			locations.length > 0
				? locations.map((location) => ({
						"@type": "Place",
						address: location,
					}))
				: undefined,
		applicantLocationRequirements:
			cleanText(detail.remote).toLowerCase() === "remote"
				? { "@type": "Country", name: "Remote" }
				: undefined,
		url: postingUrl,
		directApply: false,
	};
}

export function jobPostingJsonLdEnabled() {
	return (
		process.env.OPENOPPS_JOBPOSTING_STRUCTURED_DATA === "1" ||
		process.env.NEXT_PUBLIC_OPENOPPS_JOBPOSTING_STRUCTURED_DATA === "1"
	);
}

export function shouldNoIndexDeployment() {
	return (
		process.env.OPENOPPS_NOINDEX === "1" ||
		process.env.VERCEL_ENV === "preview" ||
		process.env.NEXT_PUBLIC_VERCEL_ENV === "preview"
	);
}

function stripHtml(value: string) {
	return removeHtmlMarkup(decodeHtmlEntities(removeHtmlMarkup(value)));
}

function removeHtmlMarkup(value: string) {
	return value
		.replace(
			/<span\b(?=[\s\S]{0,8000}?data-sheets-value=)[\s\S]{0,8000}?data-sheets-userformat="[\s\S]{0,2000}?">/gi,
			" ",
		)
		.replace(/<!--[\s\S]*?-->/g, " ")
		.replace(/<\/?[A-Za-z][A-Za-z0-9:-]*(?:\s[^>]*)?\/?>/g, " ")
		.replace(/<\/?[A-Za-z][A-Za-z0-9:-]*(?:\s[\s\S]*)?$/g, " ");
}

const HTML_NAMED_ENTITIES: Record<string, string> = {
	amp: "&",
	apos: "'",
	gt: ">",
	lt: "<",
	nbsp: " ",
	quot: '"',
};

function decodeHtmlEntities(value: string) {
	let decoded = value;
	for (let index = 0; index < 5; index += 1) {
		const next = decodeHtmlEntitiesOnce(decoded);
		if (next === decoded) {
			return next;
		}
		decoded = next;
	}
	return decoded;
}

function decodeHtmlEntitiesOnce(value: string) {
	return value.replace(
		/&(#x[0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);/g,
		(match, entity: string) => {
			const normalized = entity.toLowerCase();
			if (normalized.startsWith("#x")) {
				return decodeHtmlCodePoint(match, normalized.slice(2), 16);
			}
			if (normalized.startsWith("#")) {
				return decodeHtmlCodePoint(match, normalized.slice(1), 10);
			}
			return HTML_NAMED_ENTITIES[normalized] ?? match;
		},
	);
}

function decodeHtmlCodePoint(match: string, value: string, radix: number) {
	const codePoint = Number.parseInt(value, radix);
	if (!Number.isFinite(codePoint) || codePoint < 0 || codePoint > 0x10ffff) {
		return match;
	}
	try {
		return String.fromCodePoint(codePoint);
	} catch {
		return match;
	}
}

export function dateOrUndefined(value: string | null | undefined) {
	if (!value) {
		return undefined;
	}
	const parsed = new Date(value);
	return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}
