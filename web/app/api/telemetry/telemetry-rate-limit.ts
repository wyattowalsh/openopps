import { createHash } from "node:crypto";

import {
	extractTelemetryClientIp,
	type TelemetryTrustedProxyMode,
} from "./telemetry-client-ip";

const DEFAULT_RATE_LIMIT_MAX_BUCKETS = 4_096;

type RateLimitBucket = {
	windowStartedAt: number;
	count: number;
	lastAccessedAt: number;
};

export interface TelemetryRateLimitConfig {
	salt: string;
	rateLimitMax: number;
	rateLimitWindowMs: number;
	rateLimitMaxBuckets: number;
	trustedProxy: TelemetryTrustedProxyMode;
}

const rateLimitBuckets = new Map<string, RateLimitBucket>();

export function resetTelemetryRateLimitStateForTests() {
	rateLimitBuckets.clear();
}

export function telemetryRateLimitBucketCountForTests() {
	return rateLimitBuckets.size;
}

export function seedTelemetryRateLimitBucketsForTests(
	entries: Array<{ key: string; lastAccessedAt: number }>,
	windowStartedAt: number,
) {
	for (const entry of entries) {
		rateLimitBuckets.set(entry.key, {
			windowStartedAt,
			count: 1,
			lastAccessedAt: entry.lastAccessedAt,
		});
	}
	enforceRateLimitBucketCap(DEFAULT_RATE_LIMIT_MAX_BUCKETS);
}

export function isTelemetryRateLimited(
	request: Request,
	config: TelemetryRateLimitConfig,
) {
	if (config.rateLimitMax <= 0 || config.rateLimitWindowMs <= 0) {
		return false;
	}
	const key = rateLimitKey(request, config);
	const now = Date.now();
	pruneExpiredRateLimitBuckets(now, config.rateLimitWindowMs);
	const current = rateLimitBuckets.get(key);
	if (!current || now - current.windowStartedAt >= config.rateLimitWindowMs) {
		rateLimitBuckets.set(key, {
			windowStartedAt: now,
			count: 1,
			lastAccessedAt: now,
		});
		enforceRateLimitBucketCap(config.rateLimitMaxBuckets);
		return false;
	}
	current.count += 1;
	current.lastAccessedAt = now;
	return current.count > config.rateLimitMax;
}

function pruneExpiredRateLimitBuckets(now: number, windowMs: number) {
	const maxAge = 2 * windowMs;
	for (const [key, bucket] of rateLimitBuckets) {
		if (now - bucket.lastAccessedAt >= maxAge) {
			rateLimitBuckets.delete(key);
		}
	}
}

function enforceRateLimitBucketCap(maxBuckets: number) {
	if (rateLimitBuckets.size <= maxBuckets) {
		return;
	}
	const overflow = rateLimitBuckets.size - maxBuckets;
	const oldestKeys = [...rateLimitBuckets.entries()]
		.sort((left, right) => left[1].lastAccessedAt - right[1].lastAccessedAt)
		.slice(0, overflow)
		.map(([key]) => key);
	for (const key of oldestKeys) {
		rateLimitBuckets.delete(key);
	}
}

function rateLimitKey(request: Request, config: TelemetryRateLimitConfig) {
	const raw =
		extractTelemetryClientIp(request, config.trustedProxy) ??
			[
				request.headers.get("host") ?? "",
				request.headers.get("origin") ?? "",
				request.headers.get("user-agent") ?? "",
			].join("|");
	return createHash("sha256")
		.update(`${config.salt}:telemetry-rate:${raw}`)
		.digest("hex");
}
