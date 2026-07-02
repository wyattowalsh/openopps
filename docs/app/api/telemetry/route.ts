import { appendFile, mkdir } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { join } from "node:path";
import {
	TELEMETRY_DEFAULT_MAX_EVENT_BYTES,
	TELEMETRY_SCHEMA_VERSION,
	type TelemetryClientEvent,
	type TelemetryProperties,
	filterTelemetryContext,
	filterTelemetryPropertiesForEvent,
	isAllowedTelemetryEventName,
	normalizeTelemetryEventName,
	sanitizeTelemetryProperties,
} from "@/lib/telemetry";

import {
	extractTelemetryClientIp,
	normalizeTelemetryTrustedProxyMode,
	type TelemetryTrustedProxyMode,
} from "./telemetry-client-ip";
import { isTelemetryRateLimited } from "./telemetry-rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BATCH_EVENTS = 100;
const DEFAULT_IP_MODE = "hash";
const DEFAULT_TELEMETRY_SALT = "openopps-docs-telemetry";
const DEFAULT_RATE_LIMIT_MAX = 120;
const DEFAULT_RATE_LIMIT_WINDOW_MS = 60_000;
const DEFAULT_RATE_LIMIT_MAX_BUCKETS = 4_096;
const SENSITIVE_HEADER_PATTERN =
	/^(authorization|cookie|proxy-authorization|set-cookie|x-api-key|x-auth-token)$/i;
const HEADER_ALLOWLIST = new Set([
	"accept",
	"accept-language",
	"cf-ipcountry",
	"cf-ray",
	"host",
	"origin",
	"sec-ch-ua",
	"sec-ch-ua-mobile",
	"sec-ch-ua-platform",
	"user-agent",
	"x-forwarded-host",
	"x-forwarded-proto",
	"x-vercel-ip-city",
	"x-vercel-ip-country",
	"x-vercel-ip-country-region",
	"x-vercel-ip-timezone",
]);

type TelemetrySink = "noop" | "local-event-lake";
type TelemetryIpMode = "drop" | "hash" | "raw";

interface TelemetryRouteConfig {
	sink: TelemetrySink;
	dir?: string;
	maxRequestBytes: number;
	maxEventBytes: number;
	ipMode: TelemetryIpMode;
	salt: string;
	rateLimitMax: number;
	rateLimitWindowMs: number;
	rateLimitMaxBuckets: number;
	trustedProxy: TelemetryTrustedProxyMode;
	configError?: "telemetry_raw_ip_not_allowed" | "telemetry_salt_missing";
}

interface TelemetryEnvelope {
	schema_version: typeof TELEMETRY_SCHEMA_VERSION;
	event_id: string;
	event_name: string;
	sent_at: string;
	received_at: string;
	anonymous_id: string;
	session_id: string;
	page_id: string;
	context: TelemetryProperties;
	properties: TelemetryProperties;
	redaction_count: number;
	payload_truncated: boolean;
	request: TelemetryProperties;
}

type ExtractedTelemetryEvents = {
	events: Array<Partial<TelemetryClientEvent>>;
	submittedEventCount: number;
};

export async function POST(request: Request) {
	const config = getTelemetryRouteConfig();
	if (config.configError) {
		return jsonResponse({ ok: false, error: config.configError }, 503);
	}
	if (isTelemetryRateLimited(request, config)) {
		return jsonResponse({ ok: false, error: "telemetry_rate_limited" }, 429);
	}

	const body = await readBoundedRequestText(request, config.maxRequestBytes);
	if (!body.ok) {
		return jsonResponse(
			{ ok: false, error: "telemetry_payload_too_large" },
			413,
		);
	}

	let payload: unknown;
	try {
		payload = body.text ? JSON.parse(body.text) : {};
	} catch {
		return jsonResponse({ ok: false, error: "telemetry_json_invalid" }, 400);
	}

	const extracted = extractTelemetryEvents(payload);
	if (extracted.submittedEventCount > MAX_BATCH_EVENTS) {
		return jsonResponse(
			{ ok: false, error: "telemetry_batch_too_large" },
			413,
		);
	}
	const events = extracted.events;
	if (events.length === 0) {
		return jsonResponse({ ok: false, error: "telemetry_events_missing" }, 400);
	}

	const receivedAt = new Date().toISOString();
	const envelopes = events.map((event) =>
		buildTelemetryEnvelope(event, request, config, receivedAt),
	);

	if (config.sink === "noop") {
		return jsonResponse({
			ok: true,
			sink: "noop",
			accepted: envelopes.length,
		});
	}

	if (!config.dir) {
		return jsonResponse(
			{ ok: false, error: "telemetry_dir_missing" },
			503,
		);
	}

	try {
		await appendTelemetryEvents(config.dir, receivedAt, envelopes);
	} catch {
		return jsonResponse({ ok: false, error: "telemetry_write_failed" }, 500);
	}

	return jsonResponse({
		ok: true,
		sink: "local-event-lake",
		accepted: envelopes.length,
	});
}

function getTelemetryRouteConfig(
	env: NodeJS.ProcessEnv = process.env,
): TelemetryRouteConfig {
	const sink = normalizeTelemetrySink(env.OPENOPPS_TELEMETRY_SINK);
	const requestedIpMode = normalizeIpMode(env.OPENOPPS_TELEMETRY_IP_MODE);
	const isProduction = env.NODE_ENV === "production";
	const hasExplicitSalt = Boolean(env.OPENOPPS_TELEMETRY_SALT);
	const configError =
		isProduction && requestedIpMode === "raw"
			? "telemetry_raw_ip_not_allowed"
			: sink === "local-event-lake" && !hasExplicitSalt
				? "telemetry_salt_missing"
				: undefined;
	return {
		sink,
		dir: env.OPENOPPS_TELEMETRY_DIR,
		maxRequestBytes: readPositiveInteger(
			env.OPENOPPS_TELEMETRY_MAX_REQUEST_BYTES,
			512 * 1024,
		),
		maxEventBytes: readPositiveInteger(
			env.OPENOPPS_TELEMETRY_MAX_EVENT_BYTES,
			TELEMETRY_DEFAULT_MAX_EVENT_BYTES,
		),
		ipMode: requestedIpMode,
		salt: env.OPENOPPS_TELEMETRY_SALT || DEFAULT_TELEMETRY_SALT,
		rateLimitMax: readPositiveInteger(
			env.OPENOPPS_TELEMETRY_RATE_LIMIT_MAX,
			DEFAULT_RATE_LIMIT_MAX,
		),
		rateLimitWindowMs: readPositiveInteger(
			env.OPENOPPS_TELEMETRY_RATE_LIMIT_WINDOW_MS,
			DEFAULT_RATE_LIMIT_WINDOW_MS,
		),
		rateLimitMaxBuckets: readPositiveInteger(
			env.OPENOPPS_TELEMETRY_RATE_LIMIT_MAX_BUCKETS,
			DEFAULT_RATE_LIMIT_MAX_BUCKETS,
		),
		trustedProxy: normalizeTelemetryTrustedProxyMode(
			env.OPENOPPS_TELEMETRY_TRUSTED_PROXY,
		),
		configError,
	};
}

function buildTelemetryEnvelope(
	event: Partial<TelemetryClientEvent>,
	request: Request,
	config: TelemetryRouteConfig,
	receivedAt: string,
): TelemetryEnvelope {
	const eventName = normalizeTelemetryEventName(event.event_name) ?? "page_view";
	const properties = sanitizeTelemetryProperties(
		filterTelemetryPropertiesForEvent(eventName, event.properties ?? {}),
		{
			maxBytes: config.maxEventBytes,
		},
	);
	const context = sanitizeTelemetryProperties(filterTelemetryContext(event.context ?? {}), {
		maxBytes: Math.min(config.maxEventBytes, 16 * 1024),
	});
	const requestContext = sanitizeTelemetryProperties(
		collectRequestContext(request, config),
		{ maxBytes: Math.min(config.maxEventBytes, 16 * 1024) },
	);
	return {
		schema_version: TELEMETRY_SCHEMA_VERSION,
		event_id:
			typeof event.event_id === "string" && event.event_id
				? event.event_id
				: randomUUID(),
		event_name: eventName,
		sent_at:
			typeof event.sent_at === "string" && event.sent_at
				? event.sent_at
				: receivedAt,
		received_at: receivedAt,
		anonymous_id:
			typeof event.anonymous_id === "string" && event.anonymous_id
				? event.anonymous_id.slice(0, 160)
				: "unknown",
		session_id:
			typeof event.session_id === "string" && event.session_id
				? event.session_id.slice(0, 160)
				: "unknown",
		page_id:
			typeof event.page_id === "string" && event.page_id
				? event.page_id.slice(0, 160)
				: "unknown",
		context: context.properties,
		properties: properties.properties,
		redaction_count:
			(typeof event.redaction_count === "number" ? event.redaction_count : 0) +
			properties.redactionCount +
			context.redactionCount +
			requestContext.redactionCount,
		payload_truncated:
			Boolean(event.payload_truncated) ||
			properties.payloadTruncated ||
			context.payloadTruncated ||
			requestContext.payloadTruncated,
		request: requestContext.properties,
	};
}

function extractTelemetryEvents(payload: unknown): ExtractedTelemetryEvents {
	if (Array.isArray(payload)) {
		return {
			submittedEventCount: payload.length,
			events: payload
				.filter(isTelemetryEventLike)
				.filter((event) => isAllowedTelemetryEventName(event.event_name)),
		};
	}
	if (
		payload &&
		typeof payload === "object" &&
		Array.isArray((payload as { events?: unknown }).events)
	) {
		const submittedEvents = (payload as { events: unknown[] }).events;
		return {
			submittedEventCount: submittedEvents.length,
			events: submittedEvents
				.filter(isTelemetryEventLike)
				.filter((event) => isAllowedTelemetryEventName(event.event_name)),
		};
	}
	if (isTelemetryEventLike(payload) && isAllowedTelemetryEventName(payload.event_name)) {
		return { submittedEventCount: 1, events: [payload] };
	}
	return { submittedEventCount: 0, events: [] };
}

function isTelemetryEventLike(value: unknown): value is Partial<TelemetryClientEvent> {
	return Boolean(value && typeof value === "object");
}

function collectRequestContext(
	request: Request,
	config: TelemetryRouteConfig,
): Record<string, unknown> {
	const headers: Record<string, string> = {};
	let droppedSensitiveHeaders = 0;
	let droppedUnsupportedHeaders = 0;
	for (const [key, value] of request.headers.entries()) {
		const lowerKey = key.toLowerCase();
		if (SENSITIVE_HEADER_PATTERN.test(lowerKey)) {
			droppedSensitiveHeaders += 1;
			continue;
		}
		if (!HEADER_ALLOWLIST.has(lowerKey)) {
			droppedUnsupportedHeaders += 1;
			continue;
		}
		headers[lowerKey] = value;
	}
	return {
		path: sanitizedRequestPath(request.url),
		method: request.method,
		headers,
		dropped_sensitive_headers: droppedSensitiveHeaders,
		dropped_unsupported_headers: droppedUnsupportedHeaders,
		ip: getRequestIp(request, config),
	};
}

function sanitizedRequestPath(value: string) {
	try {
		return new URL(value).pathname;
	} catch {
		return "/api/telemetry";
	}
}

function getRequestIp(request: Request, config: TelemetryRouteConfig) {
	if (config.ipMode === "drop") {
		return undefined;
	}
	const raw = extractTelemetryClientIp(request, config.trustedProxy);
	if (!raw) {
		return undefined;
	}
	if (config.ipMode === "raw") {
		return raw;
	}
	return createHash("sha256")
		.update(`${config.salt}:${raw}`)
		.digest("hex");
}

async function appendTelemetryEvents(
	rootDir: string,
	receivedAt: string,
	envelopes: TelemetryEnvelope[],
) {
	const [date] = receivedAt.split("T");
	const [year, month, day] = date.split("-");
	const dir = join(rootDir, year, month, day);
	await mkdir(dir, { recursive: true });
	const file = join(dir, "events.ndjson");
	const lines = envelopes.map((event) => JSON.stringify(event)).join("\n");
	await appendFile(file, `${lines}\n`, "utf8");
}

async function readBoundedRequestText(
	request: Request,
	maxBytes: number,
): Promise<{ ok: true; text: string } | { ok: false }> {
	const contentLength = request.headers.get("content-length");
	if (contentLength) {
		const declaredBytes = Number(contentLength);
		if (Number.isFinite(declaredBytes) && declaredBytes > maxBytes) {
			return { ok: false };
		}
	}

	if (!request.body) {
		const text = await request.text();
		return Buffer.byteLength(text, "utf8") <= maxBytes
			? { ok: true, text }
			: { ok: false };
	}

	const reader = request.body.getReader();
	const decoder = new TextDecoder();
	let bytes = 0;
	let text = "";
	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) {
				break;
			}
			bytes += value.byteLength;
			if (bytes > maxBytes) {
				await reader.cancel();
				return { ok: false };
			}
			text += decoder.decode(value, { stream: true });
		}
		text += decoder.decode();
		return { ok: true, text };
	} finally {
		reader.releaseLock();
	}
}

function normalizeTelemetrySink(value: string | undefined): TelemetrySink {
	if (value === "local-event-lake") {
		return "local-event-lake";
	}
	return "noop";
}

function normalizeIpMode(value: string | undefined): TelemetryIpMode {
	if (value === "drop" || value === "raw" || value === "hash") {
		return value;
	}
	return DEFAULT_IP_MODE;
}

function readPositiveInteger(value: string | undefined, fallback: number) {
	const parsed = value ? Number.parseInt(value, 10) : Number.NaN;
	return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function jsonResponse(payload: unknown, status = 202) {
	return Response.json(payload, { status });
}
