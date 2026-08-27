// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExplorerFilterSelect } from "./explorer-shared";

afterEach(() => {
	cleanup();
});

const LONG_WORKPLACE = "On-site San Francisco Bay Area, California, USA";

describe("ExplorerFilterSelect", () => {
	it("constrains native selects so long option labels cannot size the control", () => {
		expect(LONG_WORKPLACE).toHaveLength(47);

		const { container } = render(
			<ExplorerFilterSelect
				label="Workplace"
				value=""
				onChange={vi.fn()}
				options={[
					{ value: "", label: "Any" },
					{ value: LONG_WORKPLACE, label: LONG_WORKPLACE },
				]}
			/>,
		);

		const select = screen.getByRole("combobox", { name: "Workplace" });
		expect(select.classList.contains("opps-select")).toBe(true);
		expect(select.classList.contains("w-full")).toBe(true);
		expect(select.classList.contains("min-w-0")).toBe(true);
		expect(select.classList.contains("max-w-full")).toBe(true);
		expect(select.classList.contains("overflow-hidden")).toBe(true);
		expect(select.classList.contains("text-ellipsis")).toBe(true);

		const label = container.querySelector("label");
		expect(label?.classList.contains("min-w-0")).toBe(true);
		expect(label?.classList.contains("max-w-full")).toBe(true);
	});
});
