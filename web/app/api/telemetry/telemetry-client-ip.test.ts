import { describe, expect, it } from "vitest";

import {
	extractTelemetryClientIp,
	normalizeTelemetryTrustedProxyMode,
} from "./telemetry-client-ip";

describe("telemetry client IP extraction", () => {
	it("normalizes trusted proxy mode configuration", () => {
		expect(normalizeTelemetryTrustedProxyMode(undefined)).toBe("none");
		expect(normalizeTelemetryTrustedProxyMode("")).toBe("none");
		expect(normalizeTelemetryTrustedProxyMode("1")).toBe("none");
		expect(normalizeTelemetryTrustedProxyMode("cloudflare")).toBe("cloudflare");
		expect(normalizeTelemetryTrustedProxyMode("vercel")).toBe("vercel");
		expect(normalizeTelemetryTrustedProxyMode("forwarded")).toBe("forwarded");
	});

	it("ignores all IP-like headers when no trusted proxy mode is configured", () => {
		const candidate = request({
			"cf-connecting-ip": "203.0.113.10",
			"x-vercel-forwarded-for": "198.51.100.10",
			"x-forwarded-for": "192.0.2.10",
			"x-real-ip": "198.18.0.10",
		});

		expect(extractTelemetryClientIp(candidate, "none")).toBeUndefined();
	});

	it("extracts only the selected trusted proxy header", () => {
		expect(
			extractTelemetryClientIp(
				request({
					"cf-connecting-ip": "203.0.113.10",
					"x-vercel-forwarded-for": "198.51.100.10",
				}),
				"cloudflare",
			),
		).toBe("203.0.113.10");
		expect(
			extractTelemetryClientIp(
				request({
					"cf-connecting-ip": "203.0.113.10",
					"x-vercel-forwarded-for": "198.51.100.10, 198.51.100.11",
				}),
				"vercel",
			),
		).toBe("198.51.100.10");
		expect(
			extractTelemetryClientIp(
				request({
					"x-forwarded-for": "192.0.2.10, 192.0.2.11",
					"x-real-ip": "198.18.0.10",
				}),
				"forwarded",
			),
		).toBe("192.0.2.10");
	});

	it("rejects malformed proxy header values", () => {
		for (const mode of ["cloudflare", "vercel", "forwarded"] as const) {
			expect(
				extractTelemetryClientIp(
					request({
						"cf-connecting-ip": "203.0.113.10:443",
						"x-vercel-forwarded-for": "not-an-ip",
						"x-forwarded-for": "not-an-ip, 203.0.113.10",
					}),
					mode,
				),
			).toBeUndefined();
		}
	});
});

function request(headers: Record<string, string>) {
	return new Request("https://docs.openopps.local/api/telemetry", {
		headers,
	});
}
