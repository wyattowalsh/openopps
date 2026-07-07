// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardPreview } from "./jobs-board-preview";
import type { SearchRow } from "@/components/openopps-search/search-types";
import type { JobDetailWithPrivateFields } from "@/lib/job-detail-utils";

afterEach(() => {
	cleanup();
});

describe("JobsBoardPreview", () => {
	it("gives the desktop close control a specific accessible name", () => {
		render(
			<JobsBoardPreview
				row={jobRow()}
				selectedJobId="job-1"
				detail={null}
				loading={false}
				error={null}
				onClose={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("button", { name: /close job preview/i }),
		).toBeTruthy();
	}, 15_000);

	it("omits javascript apply and posting links", () => {
		render(
			<JobsBoardPreview
				row={jobRow("")}
				selectedJobId="job-1"
				detail={{
					id: "job-1",
					status: "open",
					title: "Designer",
					company: "Acme",
					applyUrl: "javascript:alert(1)",
					postingUrl: "data:text/html,unsafe",
					description: "Design systems.",
				}}
				loading={false}
				error={null}
			/>,
		);

		expect(screen.queryByRole("link", { name: /^apply$/i })).toBeNull();
		expect(screen.queryByRole("link", { name: /^posting$/i })).toBeNull();
	}, 15_000);

	it("renders plain generated descriptions as text", () => {
		render(
			<JobsBoardPreview
				row={jobRow()}
				selectedJobId="job-1"
				detail={{
					id: "job-1",
					status: "open",
					title: "Designer",
					company: "Acme",
					description: "Plain generated posting description.",
				}}
				loading={false}
				error={null}
			/>,
		);

		expect(screen.getByText("Plain generated posting description.")).toBeTruthy();
	}, 15_000);

	it("renders structured job description text when it is the only full body", () => {
		render(
			<JobsBoardPreview
				row={jobRow()}
				selectedJobId="job-1"
				detail={{
					id: "job-1",
					status: "open",
					title: "Designer",
					company: "Acme",
					jobDescription: {
						description: "<p>Structured posting body only.</p>",
					},
				}}
				loading={false}
				error={null}
			/>,
		);

		expect(screen.getByText("Structured posting body only.")).toBeTruthy();
	}, 15_000);

	it("renders allowed detail fields without rendering payload snapshots", () => {
		const detail: JobDetailWithPrivateFields = {
			id: "job-1",
			status: "open",
			title: "Designer",
			company: "Acme",
			description: "Design systems.",
			experience: "Senior",
			detailTier: "T2",
			applyUrl: "https://example.test/apply",
			postingUrl: "https://example.test/jobs/1",
			payloadSnapshots: [
				{
					kind: "raw",
					payload: { secret: "raw provider payload" },
				},
			],
		};

		render(
			<JobsBoardPreview
				row={jobRow()}
				selectedJobId="job-1"
				detail={detail}
				loading={false}
				error={null}
			/>,
		);

		expect(screen.getByText("Senior")).toBeTruthy();
		expect(screen.getByText("T2")).toBeTruthy();
		expect(screen.getByText("https://example.test/apply")).toBeTruthy();
		expect(screen.getByText("https://example.test/jobs/1")).toBeTruthy();
		expect(screen.queryByText(/payload snapshot/i)).toBeNull();
		expect(screen.queryByText(/raw provider payload/i)).toBeNull();
	}, 15_000);
});

function jobRow(url = "https://example.test/jobs/1"): SearchRow {
	return [
		"job-1",
		"manual",
		"manual:acme",
		"greenhouse",
		"open",
		"Designer",
		"Acme",
		"",
		"",
		"remote",
		"remote",
		"full-time",
		"[]",
		null,
		null,
		null,
		url,
		"2026-01-01",
		"2026-01-01",
		'["manual"]',
		"",
		"",
		"2026-01-01",
	];
}
