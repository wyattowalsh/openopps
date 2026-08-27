import { describe, expect, it } from "vitest";

import type { SearchRow } from "@/components/openopps-search/search-types";
import { J } from "@/components/openopps-search/search-utils";
import {
	jobsFeedEntriesFromRows,
	renderJobsAtomFeed,
	selectLatestIndexableOpenJobs,
	xmlEscape,
} from "@/lib/jobs-feed-data";
import { siteUrl } from "@/lib/shared";

describe("jobs-feed-data", () => {
	it("keeps only indexable open rows", () => {
		const rows = [
			jobRow("keep", "open"),
			jobRow("closed", "closed"),
			jobRow("thin", "open"),
		];
		const selected = selectLatestIndexableOpenJobs({
			rows,
			indexableIds: new Set(["keep"]),
		});
		expect(selected.map((row) => row[J.id])).toEqual(["keep"]);
	});

	it("renders escaped Atom XML for latest open jobs", () => {
		const rows = [
			jobRow("a<b>", "open", "Engineer & Lead", "Acme <Inc>"),
		];
		const entries = jobsFeedEntriesFromRows(rows);
		expect(entries[0]?.url).toBe(`${siteUrl}/jobs/${encodeURIComponent("a<b>")}`);
		const xml = renderJobsAtomFeed({
			entries,
			updated: "2026-08-26T00:00:00.000Z",
		});
		expect(xml).toContain("<feed xmlns=\"http://www.w3.org/2005/Atom\">");
		expect(xml).toContain(`<link href="${siteUrl}/feed.xml" rel="self"/>`);
		expect(xml).toContain(xmlEscape("Engineer & Lead at Acme <Inc>"));
		expect(xml).not.toContain("Engineer & Lead at Acme <Inc>");
		expect(xml).toContain("/jobs/a%3Cb%3E");
	});
});

function jobRow(
	id: string,
	status: string,
	title = "Engineer",
	company = "Acme",
): SearchRow {
	const values = Array.from({ length: 30 }, () => null) as SearchRow;
	values[J.id] = id;
	values[J.status] = status;
	values[J.title] = title;
	values[J.company] = company;
	values[J.posted] = "2026-08-01T00:00:00.000000Z";
	values[J.descriptionSnippet] = "Build <things> & ships";
	return values;
}
