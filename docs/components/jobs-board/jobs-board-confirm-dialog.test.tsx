// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardConfirmDialog } from "./jobs-board-confirm-dialog";

afterEach(() => {
	cleanup();
});

describe("JobsBoardConfirmDialog", () => {
	it("renders alertdialog semantics and handles confirm", async () => {
		const user = userEvent.setup();
		const onConfirm = vi.fn();
		const onCancel = vi.fn();

		render(
			<JobsBoardConfirmDialog
				open
				title="Delete saved search?"
				description='Delete saved search "Platform"?'
				confirmLabel="Delete"
				cancelLabel="Keep"
				destructive
				onConfirm={onConfirm}
				onCancel={onCancel}
			/>,
		);

		expect(screen.getByRole("alertdialog", { name: /delete saved search/i })).toBeTruthy();
		await user.click(screen.getByRole("button", { name: /^delete$/i }));
		expect(onConfirm).toHaveBeenCalledTimes(1);
		expect(onCancel).not.toHaveBeenCalled();
	});
});