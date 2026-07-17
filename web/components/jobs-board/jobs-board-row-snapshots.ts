import type { RetainedJobDetailRecord } from "@/components/jobs-board/jobs-board-local-types";
import type { JobDetail, SearchRow } from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";

export function retainedRowSnapshot(record: RetainedJobDetailRecord): SearchRow {
	const row = record.rowSnapshot
		? [...record.rowSnapshot]
		: new Array(J.payloadHash + 1).fill(null);
	row[J.id] = record.jobId;
	row[J.status] = "open";
	row[J.title] = row[J.title] || record.detail.title || "Stale saved role";
	row[J.company] =
		row[J.company] || record.detail.company || record.detail.boardKey || "";
	row[J.source] = row[J.source] || record.detail.sourceKey || "";
	row[J.board] = row[J.board] || record.detail.boardKey || "";
	row[J.provider] = row[J.provider] || record.detail.providerId || "";
	row[J.url] = row[J.url] || record.detail.postingUrl || "";
	row[J.latestObserved] =
		row[J.latestObserved] ||
		record.detail.lastSeenAt ||
		record.detail.syncedAt ||
		record.snapshotAt ||
		"";
	row[J.syncedAt] = row[J.syncedAt] || record.detail.syncedAt || record.snapshotAt || "";
	row[J.firstSeenAt] = row[J.firstSeenAt] || record.detail.firstSeenAt || "";
	row[J.lastSeenAt] = row[J.lastSeenAt] || record.detail.lastSeenAt || "";
	row[J.closedAt] = row[J.closedAt] || record.detail.closedAt || "";
	row[J.contentHash] = row[J.contentHash] || record.detail.contentHash || "";
	row[J.payloadHash] = row[J.payloadHash] || record.detail.payloadHash || "";
	return row;
}

export function detailRowSnapshot(detail: JobDetail): SearchRow {
	const row = new Array(J.daysOpen + 1).fill(null);
	row[J.id] = detail.id;
	row[J.source] = detail.sourceKey || "";
	row[J.board] = detail.boardKey || "";
	row[J.provider] = detail.providerId || "";
	row[J.status] = detail.status || "open";
	row[J.title] = detail.title || "Untitled role";
	row[J.company] = detail.company || detail.boardKey || "";
	row[J.department] = detail.department || "";
	row[J.team] = detail.team || "";
	row[J.workplace] = detail.workplaceType || "";
	row[J.remote] = detail.remote || "";
	row[J.type] = detail.employmentType || "";
	row[J.locations] = JSON.stringify(detail.locations ?? []);
	row[J.salaryMin] = detail.salaryMin ?? null;
	row[J.salaryMax] = detail.salaryMax ?? null;
	row[J.currency] = detail.salaryCurrency || "";
	row[J.url] = detail.postingUrl || detail.applyUrl || "";
	row[J.posted] = detail.postedAt || "";
	row[J.latestObserved] =
		detail.lastSeenAt ||
		detail.updatedAt ||
		detail.versionCreatedAt ||
		detail.syncedAt ||
		"";
	row[J.sourceKeys] = JSON.stringify([detail.sourceKey].filter(Boolean));
	row[J.descriptionSnippet] = detailDescriptionSnippet(detail);
	row[J.skillTokens] = (detail.skills ?? [])
		.flatMap((skill) => [skill.name, skill.level, ...(skill.keywords ?? [])])
		.map(text)
		.filter(Boolean)
		.join(",");
	row[J.syncedAt] = detail.syncedAt || "";
	row[J.firstSeenAt] = detail.firstSeenAt || "";
	row[J.lastSeenAt] = detail.lastSeenAt || "";
	row[J.closedAt] = detail.closedAt || "";
	row[J.contentHash] = detail.contentHash || "";
	row[J.payloadHash] = detail.payloadHash || "";
	row[J.seniority] = detail.experience || "";
	return row;
}

function detailDescriptionSnippet(detail: JobDetail) {
	const value =
		text(detail.description) ||
		structuredJobDescriptionText(detail);
	return value.slice(0, 200);
}

function structuredJobDescriptionText(detail: JobDetail) {
	const value = detail.jobDescription?.description;
	if (typeof value !== "string") {
		return "";
	}
	const raw = text(value);
	if (!raw) {
		return "";
	}
	return /<\/?[A-Za-z][^>]*>/.test(raw) ? stripTags(raw) : raw;
}

function stripTags(value: string) {
	return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}