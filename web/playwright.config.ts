import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.OPENOPPS_E2E_PORT ?? 3211);
const BASE_URL = process.env.OPENOPPS_E2E_BASE_URL ?? `http://localhost:${PORT}`;
const WORKERS = Number(process.env.OPENOPPS_E2E_WORKERS ?? 2);
const WEB_SERVER_TIMEOUT = Number(
	process.env.OPENOPPS_E2E_WEB_SERVER_TIMEOUT ?? 240_000,
);
const WEB_SERVER_COMMAND =
	process.env.OPENOPPS_E2E_WEB_SERVER_COMMAND ??
	`pnpm exec next start -p ${PORT}`;

export default defineConfig({
	testDir: "./tests/e2e",
	timeout: 60_000,
	expect: {
		timeout: 15_000,
	},
	fullyParallel: true,
	forbidOnly: Boolean(process.env.CI),
	retries: process.env.CI ? 2 : 0,
	workers: WORKERS,
	reporter: process.env.CI ? [["html"], ["list"]] : "list",
	use: {
		baseURL: BASE_URL,
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
		video: "retain-on-failure",
	},
	projects: [
		{
			name: "chromium",
			use: { ...devices["Desktop Chrome"] },
		},
		{
			name: "mobile-chromium",
			use: {
				...devices["Pixel 5"],
				viewport: { width: 390, height: 844 },
			},
		},
	],
	webServer: process.env.OPENOPPS_E2E_BASE_URL
		? undefined
		: {
				command: WEB_SERVER_COMMAND,
				url: BASE_URL,
				reuseExistingServer: !process.env.CI,
				timeout: WEB_SERVER_TIMEOUT,
			},
});
