import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";
import {
	resetTelemetryRateLimitStateForTests,
	seedTelemetryRateLimitBucketsForTests,
	telemetryRateLimitBucketCountForTests,
} from "./telemetry-rate-limit";

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllEnvs();
	resetTelemetryRateLimitStateForTests();
});

describe("telemetry route", () => {
	it("defaults to noop and accepts valid batches", async () => {
		const response = await POST(
			request({
				events: [event({ event_name: "page_view" })],
				reason: "test",
			}),
		);

		expect(response.status).toBe(202);
		await expect(response.json()).resolves.toMatchObject({
			ok: true,
			sink: "noop",
			accepted: 1,
		});
	});

	it("rejects payloads above the configured request byte limit", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_MAX_REQUEST_BYTES", "16");

		const response = await POST(
			request({ events: [event({ properties: { large: "x".repeat(100) } })] }),
		);

		expect(response.status).toBe(413);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_payload_too_large",
		});
	});

	it("rejects declared oversized payloads without reading the body stream", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_MAX_REQUEST_BYTES", "16");
		let getReaderCalled = false;
		const body = {
			getReader() {
				getReaderCalled = true;
				throw new Error("body should not be read");
			},
		};

		const oversizedRequest = {
			body: body as unknown as ReadableStream<Uint8Array>,
			headers: new Headers({
				"content-length": "17",
				"content-type": "application/json",
			}),
			method: "POST",
			url: "https://docs.openopps.local/api/telemetry",
		} as Request;

		const response = await POST(oversizedRequest);

		expect(response.status).toBe(413);
		expect(getReaderCalled).toBe(false);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_payload_too_large",
		});
	});

	it("cancels streamed payloads once they exceed the request byte limit", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_MAX_REQUEST_BYTES", "16");
		let canceled = false;
		const encoder = new TextEncoder();
		const body = new ReadableStream<Uint8Array>({
			pull(controller) {
				controller.enqueue(encoder.encode("x".repeat(20)));
			},
			cancel() {
				canceled = true;
			},
		});

		const response = await POST(
			new Request("https://docs.openopps.local/api/telemetry", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body,
				duplex: "half",
			} as RequestInit),
		);

		expect(response.status).toBe(413);
		expect(canceled).toBe(true);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_payload_too_large",
		});
	});

	it("persists normalized event names instead of raw submitted names", async () => {
		const dir = await mkdtemp(join(tmpdir(), "openopps-telemetry-"));
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");
		vi.stubEnv("OPENOPPS_TELEMETRY_DIR", dir);
		vi.stubEnv("OPENOPPS_TELEMETRY_SALT", "test-salt");

		try {
			const response = await POST(
				request({
					events: [
						event({
							event_name: " jobs.filters changed ",
							properties: {
								keys: ["source"],
								hasSelection: true,
								private: "drop me",
							},
						}),
					],
				}),
			);

			expect(response.status).toBe(202);
			const files = await findEventFiles(dir);
			const written = JSON.parse((await readFile(files[0], "utf8")).trim());
			expect(written.event_name).toBe("jobs.filters_changed");
			expect(written.properties).toEqual({
				keys: ["source"],
				hasSelection: true,
			});
		} finally {
			await rm(dir, { force: true, recursive: true });
		}
	});

	it("requires an explicit salt for local event-lake writes", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");

		const response = await POST(request({ events: [event()] }));

		expect(response.status).toBe(503);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_salt_missing",
		});
	});

	it("requires a telemetry directory for local event-lake writes", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");
		vi.stubEnv("OPENOPPS_TELEMETRY_SALT", "test-salt");

		const response = await POST(request({ events: [event()] }));

		expect(response.status).toBe(503);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_dir_missing",
		});
	});

	it("appends sanitized NDJSON events to a partitioned local event lake", async () => {
		const dir = await mkdtemp(join(tmpdir(), "openopps-telemetry-"));
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");
		vi.stubEnv("OPENOPPS_TELEMETRY_DIR", dir);
		vi.stubEnv("OPENOPPS_TELEMETRY_SALT", "test-salt");

		try {
			const response = await POST(
				request(
					{
						events: [
							event({
								event_name: "jobs.filters_changed",
								context: {
									path: "/jobs",
									search: "?token=abc123&source=greenhouse",
								},
								properties: {
									keys: ["source"],
									hasSelection: false,
									source: "greenhouse",
									notes: "private note",
									apiKey: "sk_test_12345678901234567890",
								},
							}),
						],
					},
					{
						authorization: "Bearer should-not-be-written",
						"user-agent": "vitest",
						"cf-connecting-ip": "203.0.113.10",
						"x-random-debug-header": "ignored",
					},
				),
			);

			expect(response.status).toBe(202);
			await expect(response.json()).resolves.toMatchObject({
				ok: true,
				sink: "local-event-lake",
				accepted: 1,
			});

			const files = await findEventFiles(dir);
			expect(files).toHaveLength(1);
			const lines = (await readFile(files[0], "utf8")).trim().split("\n");
			expect(lines).toHaveLength(1);
			const written = JSON.parse(lines[0]);
			expect(written).toMatchObject({
				schema_version: 1,
				event_name: "jobs.filters_changed",
				properties: {
					keys: ["source"],
					hasSelection: false,
				},
				context: {
					path: "/jobs",
				},
				request: {
					headers: {
						"user-agent": "vitest",
					},
					dropped_sensitive_headers: 1,
					dropped_unsupported_headers: 3,
				},
			});
			expect(written.request.ip).toBeUndefined();
			expect(JSON.stringify(written)).not.toContain("should-not-be-written");
			expect(JSON.stringify(written)).not.toContain("203.0.113.10");
			expect(JSON.stringify(written)).not.toContain("private note");
			expect(JSON.stringify(written)).not.toContain("greenhouse");
			expect(JSON.stringify(written)).not.toContain("sk_test");
		} finally {
			await rm(dir, { force: true, recursive: true });
		}
	});

	it("persists hashed request IPs only for an explicit trusted proxy mode", async () => {
		const dir = await mkdtemp(join(tmpdir(), "openopps-telemetry-"));
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");
		vi.stubEnv("OPENOPPS_TELEMETRY_DIR", dir);
		vi.stubEnv("OPENOPPS_TELEMETRY_SALT", "test-salt");
		vi.stubEnv("OPENOPPS_TELEMETRY_TRUSTED_PROXY", "cloudflare");

		try {
			const response = await POST(
				request(
					{ events: [event()] },
					{
						"user-agent": "vitest",
						"cf-connecting-ip": "203.0.113.10",
					},
				),
			);

			expect(response.status).toBe(202);
			const files = await findEventFiles(dir);
			const written = JSON.parse((await readFile(files[0], "utf8")).trim());
			expect(written.request.ip).toMatch(/^[a-f0-9]{64}$/);
			expect(JSON.stringify(written)).not.toContain("203.0.113.10");
		} finally {
			await rm(dir, { force: true, recursive: true });
		}
	});

	it("drops referer headers and request query strings from persisted context", async () => {
		const dir = await mkdtemp(join(tmpdir(), "openopps-telemetry-"));
		vi.stubEnv("OPENOPPS_TELEMETRY_SINK", "local-event-lake");
		vi.stubEnv("OPENOPPS_TELEMETRY_DIR", dir);
		vi.stubEnv("OPENOPPS_TELEMETRY_SALT", "test-salt");

		try {
			const response = await POST(
				request(
					{ events: [event()] },
					{
						referer: "https://example.test/?token=secret",
						"user-agent": "vitest",
					},
					"https://docs.openopps.local/api/telemetry?job=private",
				),
			);

			expect(response.status).toBe(202);
			const files = await findEventFiles(dir);
			const written = JSON.parse((await readFile(files[0], "utf8")).trim());
			expect(written.request).toMatchObject({
				path: "/api/telemetry",
				headers: {
					"user-agent": "vitest",
				},
			});
			expect(JSON.stringify(written)).not.toContain("referer");
			expect(JSON.stringify(written)).not.toContain("token=secret");
			expect(JSON.stringify(written)).not.toContain("job=private");
		} finally {
			await rm(dir, { force: true, recursive: true });
		}
	});

	it("rejects submitted batches over the event count limit before filtering", async () => {
		const response = await POST(
			request({
				events: Array.from({ length: 101 }, () => event({ event_name: "page_view" })),
			}),
		);

		expect(response.status).toBe(413);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_batch_too_large",
		});
	});

	it("rejects raw IP retention in production config", async () => {
		vi.stubEnv("NODE_ENV", "production");
		vi.stubEnv("OPENOPPS_TELEMETRY_IP_MODE", "raw");

		const response = await POST(request({ events: [event()] }));

		expect(response.status).toBe(503);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_raw_ip_not_allowed",
		});
	});

	it("rate limits public telemetry posts by request fingerprint", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_MAX", "1");
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_WINDOW_MS", "60000");
		vi.stubEnv("OPENOPPS_TELEMETRY_TRUSTED_PROXY", "forwarded");

		const headers = {
			"user-agent": "vitest",
			"x-forwarded-for": "203.0.113.10",
		};
		const first = await POST(request({ events: [event()] }, headers));
		const second = await POST(request({ events: [event()] }, headers));

		expect(first.status).toBe(202);
		expect(second.status).toBe(429);
		await expect(second.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_rate_limited",
		});
	});

	it("ignores spoofed IP-like headers unless a trusted proxy mode is configured", async () => {
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_MAX", "1");
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_WINDOW_MS", "60000");

		const spoofedA = {
			"user-agent": "vitest",
			"cf-connecting-ip": "203.0.113.10",
			"x-vercel-forwarded-for": "198.51.100.10",
			"x-forwarded-for": "203.0.113.10",
			"x-real-ip": "198.18.0.10",
		};
		const spoofedB = {
			"user-agent": "vitest",
			"cf-connecting-ip": "203.0.113.11",
			"x-vercel-forwarded-for": "198.51.100.11",
			"x-forwarded-for": "198.18.0.1",
			"x-real-ip": "198.18.0.11",
		};

		const firstSpoofed = await POST(request({ events: [event()] }, spoofedA));
		const secondSpoofed = await POST(request({ events: [event()] }, spoofedB));
		expect(firstSpoofed.status).toBe(202);
		expect(secondSpoofed.status).toBe(429);
	});

	it("rate limits separately by explicitly configured trusted proxy mode", async () => {
		const scenarios = [
			{
				mode: "cloudflare",
				first: { "cf-connecting-ip": "203.0.113.10" },
				second: { "cf-connecting-ip": "203.0.113.11" },
			},
			{
				mode: "vercel",
				first: { "x-vercel-forwarded-for": "198.51.100.10" },
				second: { "x-vercel-forwarded-for": "198.51.100.11" },
			},
			{
				mode: "forwarded",
				first: { "x-forwarded-for": "192.0.2.10, 10.0.0.1" },
				second: { "x-forwarded-for": "192.0.2.11, 10.0.0.1" },
			},
		] as const;

		for (const scenario of scenarios) {
			resetTelemetryRateLimitStateForTests();
			vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_MAX", "1");
			vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_WINDOW_MS", "60000");
			vi.stubEnv("OPENOPPS_TELEMETRY_TRUSTED_PROXY", scenario.mode);

			const first = await POST(
				request({ events: [event()] }, { "user-agent": "vitest", ...scenario.first }),
			);
			const secondDifferentIp = await POST(
				request({ events: [event()] }, { "user-agent": "vitest", ...scenario.second }),
			);
			const secondSameIp = await POST(
				request({ events: [event()] }, { "user-agent": "vitest", ...scenario.second }),
			);

			expect(first.status).toBe(202);
			expect(secondDifferentIp.status).toBe(202);
			expect(secondSameIp.status).toBe(429);
		}
	});

	it("allows a rate-limited fingerprint after the configured window expires", async () => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date("2026-06-30T12:00:00.000Z"));
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_MAX", "1");
		vi.stubEnv("OPENOPPS_TELEMETRY_RATE_LIMIT_WINDOW_MS", "60000");
		vi.stubEnv("OPENOPPS_TELEMETRY_TRUSTED_PROXY", "forwarded");

		const headers = {
			"user-agent": "vitest",
			"x-forwarded-for": "203.0.113.10",
		};
		const first = await POST(request({ events: [event()] }, headers));
		const second = await POST(request({ events: [event()] }, headers));
		vi.advanceTimersByTime(60_000);
		const third = await POST(request({ events: [event()] }, headers));

		expect(first.status).toBe(202);
		expect(second.status).toBe(429);
		expect(third.status).toBe(202);
	});

	it("evicts stale rate-limit buckets and caps map growth", () => {
		const now = Date.now();
		seedTelemetryRateLimitBucketsForTests(
			Array.from({ length: 10_050 }, (_, index) => ({
				key: `bucket-${index}`,
				lastAccessedAt: now - index,
			})),
			now,
		);

		expect(telemetryRateLimitBucketCountForTests()).toBeLessThanOrEqual(4_096);
	});

	it("rejects batches after disallowed events are filtered out", async () => {
		const response = await POST(
			request({ events: [event({ event_name: "jobs.filter" })] }),
		);

		expect(response.status).toBe(400);
		await expect(response.json()).resolves.toMatchObject({
			ok: false,
			error: "telemetry_events_missing",
		});
	});
});

function request(
	payload: unknown,
	headers: Record<string, string> = {},
	url = "https://docs.openopps.local/api/telemetry",
) {
	return new Request(url, {
		method: "POST",
		headers: {
			"content-type": "application/json",
			...headers,
		},
		body: JSON.stringify(payload),
	});
}

function event(overrides: Record<string, unknown> = {}) {
	return {
		schema_version: 1,
		event_id: "event-1",
		event_name: "page_view",
		sent_at: "2026-06-30T12:00:00.000Z",
		anonymous_id: "anon-1",
		session_id: "session-1",
		page_id: "page-1",
		context: {},
		properties: {},
		redaction_count: 0,
		payload_truncated: false,
		...overrides,
	};
}

async function findEventFiles(root: string): Promise<string[]> {
	const entries = await readdir(root, { withFileTypes: true });
	const files = await Promise.all(
		entries.map(async (entry) => {
			const path = join(root, entry.name);
			if (entry.isDirectory()) {
				return findEventFiles(path);
			}
			return entry.name === "events.ndjson" ? [path] : [];
		}),
	);
	return files.flat();
}
