// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardLocalDataPanel } from "./jobs-board-local-data-panel";
import type {
	JobsLocalSettings,
	JobsLocalSummary,
} from "./jobs-board-local-state";

afterEach(() => {
	cleanup();
});

describe("JobsBoardLocalDataPanel", () => {
	it("moves focus into the dialog and closes from Escape", async () => {
		const opener = document.createElement("button");
		opener.textContent = "Open settings";
		document.body.append(opener);
		opener.focus();
		const onClose = vi.fn();

	renderPanel({ onClose });

	await waitFor(() =>
		expect(screen.getByLabelText("Close app settings")).toBe(
			document.activeElement,
		),
	);

		fireEvent.keyDown(document, { key: "Escape" });
		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it("keeps Tab focus inside the dialog", async () => {
		const user = userEvent.setup();
	renderPanel();

	await waitFor(() =>
		expect(screen.getByLabelText("Close app settings")).toBe(
			document.activeElement,
		),
	);

	await user.tab({ shift: true });
	expect(screen.getByRole("button", { name: "Clear all local data" })).toBe(
		document.activeElement,
	);
	await user.tab();
	expect(screen.getByLabelText("Close app settings")).toBe(
		document.activeElement,
	);
	}, 15_000);

	it("requires confirmation before replace import", async () => {
		const user = userEvent.setup();
		const onImport = vi.fn().mockResolvedValue({ ok: true });
		renderPanel({ onImport });

	await user.selectOptions(screen.getByLabelText("Import mode"), "replace");
	fireEvent.change(screen.getByLabelText("Import local data JSON"), {
		target: { value: '{"source":"openopps.jobs.local"}' },
	});

	const replaceButton = screen.getByRole("button", { name: "Replace Data" });
	expect(replaceButton).toHaveProperty("disabled", true);
		expect(onImport).not.toHaveBeenCalled();

		await user.click(screen.getByLabelText(/Replace all saved/));
		await user.click(replaceButton);

		await waitFor(() =>
			expect(onImport).toHaveBeenCalledWith(
				'{"source":"openopps.jobs.local"}',
				"replace",
			),
		);
	}, 15_000);
});

function renderPanel(
	overrides: Partial<ComponentProps<typeof JobsBoardLocalDataPanel>> = {},
) {
	return render(
		<JobsBoardLocalDataPanel
			open
			settings={settings}
			storageStatus="available"
			summary={summary}
			onClose={vi.fn()}
			onSettingsChange={vi.fn()}
			onClearCategory={vi.fn()}
			onExport={() => "{}"}
			onImport={vi.fn().mockResolvedValue({ ok: true })}
			{...overrides}
		/>,
	);
}

const settings: JobsLocalSettings = {
	schemaVersion: 1,
	fullDetailRetentionMonths: 6,
	showHidden: false,
	hideViewed: false,
	dismissedStorageNotice: false,
};

const summary: JobsLocalSummary = {
	viewed: 0,
	saved: 0,
	hidden: 0,
	applied: 0,
	noted: 0,
	savedSearches: 0,
	retainedDetails: 0,
	staleDurableJobs: 0,
	approximateBytes: 0,
};
