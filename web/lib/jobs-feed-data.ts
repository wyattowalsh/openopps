import { cache } from "react";

import type { SearchRow } from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";
import { canonicalJobUrl, dateOrUndefined } from "@/lib/job-detail-utils";
import { createPublicDataSnapshotClient } from "@/lib/openopps-snapshot-client.server";
import { canonicalSiteUrl, jobsFeedUrl, siteWideCopy } from "@/lib/site-metadata";

export type JobsFeedEntry = {
	id: string;
	title: string;
	company: string;
	url: string;
	updated: string;
	summary: string;
};

const getSnapshotClient = cache(() => createPublicDataSnapshotClient());

export function xmlEscape(value: string) {
	return value.replace(
		/[&<>"']/g,
		(character) =>
			({
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&apos;",
			})[character]!,
	);
}

export function selectLatestIndexableOpenJobs(input: {
	rows: SearchRow[];
	indexableIds: ReadonlySet<string>;
}) {
	return input.rows.filter((row) => {
		const id = text(row[J.id]);
		const status = text(row[J.status]).toLowerCase();
		return Boolean(id) && status === "open" && input.indexableIds.has(id);
	});
}

export function jobsFeedEntriesFromRows(rows: SearchRow[]): JobsFeedEntry[] {
	return rows.map((row) => {
		const id = text(row[J.id]);
		const title = text(row[J.title]) || "Untitled role";
		const company = text(row[J.company]);
		const updated =
			dateOrUndefined(text(row[J.latestObserved]) || text(row[J.posted]))?.toISOString() ??
			new Date(0).toISOString();
		const summary = text(row[J.descriptionSnippet]) || `${title}${company ? ` at ${company}` : ""}`;
		return {
			id,
			title: company ? `${title} at ${company}` : title,
			company,
			url: canonicalJobUrl(id),
			updated,
			summary,
		};
	});
}

export function renderJobsAtomFeed(input: {
	entries: JobsFeedEntry[];
	updated: string;
}) {
	const self = jobsFeedUrl();
	const home = canonicalSiteUrl("/");
	const entryXml = input.entries.map((entry) =>
		[
			"<entry>",
			`<title>${xmlEscape(entry.title)}</title>`,
			`<link href="${xmlEscape(entry.url)}"/>`,
			`<id>${xmlEscape(entry.url)}</id>`,
			`<updated>${xmlEscape(entry.updated)}</updated>`,
			`<summary>${xmlEscape(entry.summary)}</summary>`,
			"</entry>",
		].join("\n"),
	);
	return [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<feed xmlns="http://www.w3.org/2005/Atom">',
		`<title>${xmlEscape("OpenOpps latest open jobs")}</title>`,
		`<subtitle>${xmlEscape(siteWideCopy.description)}</subtitle>`,
		`<link href="${xmlEscape(self)}" rel="self"/>`,
		`<link href="${xmlEscape(home)}"/>`,
		`<id>${xmlEscape(self)}</id>`,
		`<updated>${xmlEscape(input.updated)}</updated>`,
		...entryXml,
		"</feed>",
		"",
	].join("\n");
}

export async function getLatestOpenJobsAtomFeed() {
	const client = getSnapshotClient();
	const [manifest, indexableIds] = await Promise.all([
		client.getSearchManifest(),
		client.getIndexableJobIds(),
	]);
	const initialPath = manifest.entities.jobs.initialPath;
	if (!initialPath) {
		return {
			body: renderJobsAtomFeed({
				entries: [],
				updated: dateOrUndefined(manifest.snapshotAt)?.toISOString() ?? new Date(0).toISOString(),
			}),
			updated: manifest.snapshotAt,
		};
	}
	const chunk = await client.getSearchChunk(initialPath);
	const rows = selectLatestIndexableOpenJobs({
		rows: chunk.rows,
		indexableIds: new Set(indexableIds),
	});
	const updated =
		dateOrUndefined(manifest.snapshotAt)?.toISOString() ?? new Date(0).toISOString();
	return {
		body: renderJobsAtomFeed({
			entries: jobsFeedEntriesFromRows(rows),
			updated,
		}),
		updated: manifest.snapshotAt,
	};
}
