import { afterEach, describe, expect, it, vi } from "vitest";

import {
	createTelemetryClient,
	resetTelemetryClientForTests,
	isAllowedTelemetryEventName,
	sanitizeTelemetryProperties,
} from "./telemetry";

afterEach(() => {
	resetTelemetryClientForTests();
	vi.unstubAllEnvs();
	vi.unstubAllGlobals();
});

describe("telemetry sanitizer", () => {
	it("redacts secret-like keys and values recursively", () => {
		const sanitized = sanitizeTelemetryProperties({
			filter: "provider:greenhouse",
			nested: {
				apiKey: "sk_test_12345678901234567890",
				authorization: "Bearer abcdefghijklmnopqrstuvwxyz",
			},
			values: ["safe", "github_pat_1234567890abcdef1234567890"],
		});

		expect(sanitized.properties).toMatchObject({
			filter: "provider:greenhouse",
			nested: {
				apiKey: "[REDACTED]",
				authorization: "[REDACTED]",
			},
			values: ["safe", "[REDACTED]"],
		});
		expect(sanitized.redactionCount).toBeGreaterThanOrEqual(3);
	});

	it("redacts sensitive query parameters in URLs", () => {
		const sanitized = sanitizeTelemetryProperties({
			url: "https://example.com/jobs?token=abc123&source=greenhouse",
			path: "/jobs?api_key=abc123&provider=lever",
		});

		expect(sanitized.properties.url).toBe(
			"https://example.com/jobs?token=%5BREDACTED%5D&source=greenhouse",
		);
		expect(sanitized.properties.path).toBe(
			"/jobs?api_key=%5BREDACTED%5D&provider=lever",
		);
		expect(sanitized.redactionCount).toBe(2);
	});

	it("replaces oversized payloads with truncation metadata", () => {
		const sanitized = sanitizeTelemetryProperties(
			{ large: "x".repeat(200) },
			{ maxBytes: 32 },
		);

		expect(sanitized.payloadTruncated).toBe(true);
		expect(sanitized.properties._truncated).toBe(true);
	});
});

describe("telemetry client", () => {
	it("exposes an explicit event-name allowlist", () => {
		expect(isAllowedTelemetryEventName("jobs.local_flag_changed")).toBe(true);
		expect(isAllowedTelemetryEventName("jobs.filter")).toBe(false);
	});

	it("noops by default", async () => {
		const transport = vi.fn();
		const client = createTelemetryClient({ transport });

		client.track("page_view", { path: "/" });
		await client.flush("test");

		expect(client.pendingCount()).toBe(0);
		expect(transport).not.toHaveBeenCalled();
	});

	it("honors the analytics kill switch even when explicitly enabled", async () => {
		vi.stubEnv("NEXT_PUBLIC_OPENOPPS_ANALYTICS_DISABLED", "true");
		const transport = vi.fn();
		const client = createTelemetryClient({ enabled: true, transport });

		client.track("page_view", { path: "/" });
		await client.flush("test");

		expect(client.pendingCount()).toBe(0);
		expect(transport).not.toHaveBeenCalled();
	});

	it("queues events and flushes through an injected transport", async () => {
		const transport = vi.fn().mockResolvedValue(undefined);
		const client = createTelemetryClient({
			enabled: true,
			endpoint: "/api/telemetry",
			flushIntervalMs: 0,
			transport,
			idGenerator: deterministicIds(),
			now: () => new Date("2026-06-30T12:00:00.000Z"),
		});

		client.track("jobs.local_flag_changed", {
			flag: "saved",
			enabled: true,
			source: "greenhouse",
			notes: "private note",
			secretToken: "github_pat_1234567890abcdef1234567890",
		});
		await client.flush("test");

		expect(transport).toHaveBeenCalledWith(
			"/api/telemetry",
			expect.objectContaining({
				reason: "test",
				events: [
					expect.objectContaining({
						event_name: "jobs.local_flag_changed",
						properties: expect.objectContaining({
							flag: "saved",
							enabled: true,
						}),
						redaction_count: expect.any(Number),
					}),
				],
			}),
		);
		const event = transport.mock.calls[0][1].events[0];
		expect(event.properties).not.toHaveProperty("source");
		expect(event.properties).not.toHaveProperty("notes");
		expect(event.properties).not.toHaveProperty("secretToken");
	});

	it("drops events outside the allowlist", async () => {
		const transport = vi.fn().mockResolvedValue(undefined);
		const client = createTelemetryClient({
			enabled: true,
			flushIntervalMs: 0,
			transport,
			idGenerator: deterministicIds(),
		});

		client.track("jobs.filter", { source: "greenhouse" });
		await client.flush("test");

		expect(client.pendingCount()).toBe(0);
		expect(transport).not.toHaveBeenCalled();
	});

	it("drops raw URL context before transport", async () => {
		const transport = vi.fn().mockResolvedValue(undefined);
		const client = createTelemetryClient({
			enabled: true,
			flushIntervalMs: 0,
			transport,
			idGenerator: deterministicIds(),
		});

		client.setRouteContext({
			path: "/",
			search: "?q=private-search",
			url: "https://openopps.dev/?q=private-search",
			referrer: "https://example.test/?token=secret",
			title: "OpenOpps",
		});
		client.track("page_view", {
			path: "/",
			search: "?q=private-search",
			referrer: "https://example.test/?token=secret",
			title: "OpenOpps",
		});
		await client.flush("test");

		const event = transport.mock.calls[0][1].events[0];
		expect(event.context).toMatchObject({ path: "/", title: "OpenOpps" });
		expect(event.context).not.toHaveProperty("search");
		expect(event.context).not.toHaveProperty("url");
		expect(event.context).not.toHaveProperty("referrer");
		expect(event.properties).toEqual({ path: "/", title: "OpenOpps" });
	});

	it("uses sendBeacon when the default transport can enqueue the payload", async () => {
		const sendBeacon = vi.fn().mockReturnValue(true);
		vi.stubGlobal("navigator", { sendBeacon });
		const fetchMock = vi.fn();
		vi.stubGlobal("fetch", fetchMock);
		const client = createTelemetryClient({
			enabled: true,
			flushIntervalMs: 0,
			idGenerator: deterministicIds(),
		});

		client.track("page_view", { path: "/" });
		await client.flush("beacon");

		expect(sendBeacon).toHaveBeenCalledOnce();
		expect(sendBeacon.mock.calls[0][0]).toBe("/api/telemetry");
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("falls back to fetch keepalive when sendBeacon declines", async () => {
		vi.stubGlobal("navigator", {
			sendBeacon: vi.fn().mockReturnValue(false),
		});
		const fetchMock = vi
			.fn()
			.mockResolvedValue(new Response(null, { status: 202 }));
		vi.stubGlobal("fetch", fetchMock);
		const client = createTelemetryClient({
			enabled: true,
			flushIntervalMs: 0,
			idGenerator: deterministicIds(),
		});

		client.track("page_view", { path: "/" });
		await client.flush("fetch");

		expect(fetchMock).toHaveBeenCalledWith(
			"/api/telemetry",
			expect.objectContaining({
				method: "POST",
				keepalive: true,
			}),
		);
	});
});

function deterministicIds() {
	let index = 0;
	return () => {
		index += 1;
		return `id-${index}`;
	};
}
