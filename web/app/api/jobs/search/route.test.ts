import { describe, expect, it } from "vitest";

import { GET, POST } from "./route";

describe("retired jobs search route", () => {
	it.each([
		["GET", GET],
		["POST", POST],
	] as const)("fails closed for stale %s clients without loading the corpus", async (_method, route) => {
		const response = await route();

		expect(response.status).toBe(410);
		expect(response.headers.get("Cache-Control")).toBe("no-store");
		await expect(response.json()).resolves.toEqual({
			error:
				"Jobs search moved to the release-pinned browser worker; refresh the application to use the current client.",
			code: "browser_worker_required",
		});
	});
});
