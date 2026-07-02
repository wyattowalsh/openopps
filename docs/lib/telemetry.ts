export const TELEMETRY_SCHEMA_VERSION = 1;
export const TELEMETRY_DEFAULT_ENDPOINT = "/api/telemetry";
export const TELEMETRY_DEFAULT_MAX_EVENT_BYTES = 64 * 1024;

const DEFAULT_QUEUE_SIZE = 100;
const DEFAULT_BATCH_SIZE = 20;
const DEFAULT_FLUSH_INTERVAL_MS = 1000;
const ANONYMOUS_ID_KEY = "openopps.telemetry.anonymous_id";
const SESSION_ID_KEY = "openopps.telemetry.session_id";

const SECRET_KEY_PATTERN =
	/(^|[_\-.])(api[_\-.]?key|authorization|bearer|cookie|credential|jwt|pass(word|wd)?|private[_\-.]?key|refresh[_\-.]?token|secret|session|token)([_\-.]|$)/i;
const SECRET_VALUE_PATTERNS = [
	/\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/i,
	/\b(?:sk|rk|pk|ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{12,}\b/i,
	/\bxox(?:b|p|a|r|s)-[A-Za-z0-9-]{12,}\b/i,
	/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/,
];

type TelemetryPrimitive = string | number | boolean | null;
export type TelemetryValue =
	| TelemetryPrimitive
	| TelemetryValue[]
	| { [key: string]: TelemetryValue };
export type TelemetryProperties = Record<string, TelemetryValue>;

export interface SanitizedTelemetryProperties {
	properties: TelemetryProperties;
	redactionCount: number;
	payloadTruncated: boolean;
	byteLength: number;
}

export interface TelemetryContext {
	path?: string;
	search?: string;
	url?: string;
	referrer?: string;
	title?: string;
	viewport?: { width: number; height: number };
	screen?: { width: number; height: number; pixelRatio: number };
	timezone?: string;
	language?: string;
	languages?: string[];
	userAgent?: string;
	connection?: TelemetryProperties;
}

export interface TelemetryClientEvent {
	schema_version: typeof TELEMETRY_SCHEMA_VERSION;
	event_id: string;
	event_name: string;
	sent_at: string;
	anonymous_id: string;
	session_id: string;
	page_id: string;
	context: TelemetryContext;
	properties: TelemetryProperties;
	redaction_count: number;
	payload_truncated: boolean;
}

export interface TelemetryRequestPayload {
	events: TelemetryClientEvent[];
	reason?: string;
}

export const TELEMETRY_EVENT_PROPERTY_ALLOWLIST = {
	page_view: ["path", "title"],
	"explorer.inspector_closed": ["activeFilters", "entity"],
	"explorer.inspector_opened": ["activeFilters", "entity"],
	"explorer.manifest_error": ["message"],
	"explorer.manifest_loaded": [
		"boards",
		"hasDashboard",
		"jobs",
		"manifestVersion",
		"providers",
		"suggestions",
	],
	"jobs.detail_error": ["hasSelectedJob", "message"],
	"jobs.detail_loaded": [
		"hasDescription",
		"payloadSnapshots",
		"providerIdPresent",
		"sourceKeyPresent",
	],
	"jobs.filters_changed": ["hasSelection", "keys"],
	"jobs.filters_cleared": ["activeFilterCount", "hasSelection"],
	"jobs.full_index_error": ["message"],
	"jobs.full_index_confirmed": [
		"activeFilterCount",
		"hasSelection",
		"jobCount",
	],
	"jobs.full_index_loaded": ["reason", "rows"],
	"jobs.full_index_retry": ["activeFilterCount", "hasSelection"],
	"jobs.index_error": ["message"],
	"jobs.index_loaded": ["initialRows", "manifestVersion", "totalRows"],
	"jobs.local_clear_clicked": ["category"],
	"jobs.local_export_clicked": ["category", "recordCountBucket"],
	"jobs.local_flag_changed": ["enabled", "flag"],
	"jobs.local_import_completed": ["mode", "recordCountBucket", "success"],
	"jobs.local_import_started": ["mode"],
	"jobs.outbound_clicked": [
		"hasUrl",
		"kind",
		"providerIdPresent",
		"sourceKeyPresent",
	],
	"jobs.preview_closed": ["hadSelection"],
	"jobs.result_selected": ["hadPreviousSelection"],
	"jobs.saved_search_created": ["activeFilterCount", "matchBucket"],
	"jobs.saved_search_deleted": [],
	"jobs.saved_search_restored": ["newMatchBucket"],
	"jobs.saved_search_reviewed": ["matchBucket"],
} as const satisfies Record<string, readonly string[]>;

export type TelemetryEventName = keyof typeof TELEMETRY_EVENT_PROPERTY_ALLOWLIST;

const TELEMETRY_CONTEXT_ALLOWLIST = new Set([
	"connection",
	"language",
	"languages",
	"path",
	"screen",
	"timezone",
	"title",
	"userAgent",
	"viewport",
]);

export interface TelemetryClientOptions {
	enabled?: boolean;
	endpoint?: string;
	flushIntervalMs?: number;
	maxQueueSize?: number;
	batchSize?: number;
	maxEventBytes?: number;
	now?: () => Date;
	idGenerator?: () => string;
	transport?: TelemetryTransport;
}

export interface TelemetryClient {
	track: (eventName: string, properties?: Record<string, unknown>) => void;
	flush: (reason?: string) => Promise<void>;
	pendingCount: () => number;
	setRouteContext: (context: TelemetryContext) => void;
	dispose: () => void;
}

export type TelemetryTransport = (
	endpoint: string,
	payload: TelemetryRequestPayload,
) => Promise<void>;

interface SanitizeState {
	redactionCount: number;
	payloadTruncated: boolean;
	maxDepth: number;
	maxArrayItems: number;
	maxObjectEntries: number;
}

let defaultClient: TelemetryClient | undefined;

export function sanitizeTelemetryProperties(
	input: TelemetryContext | TelemetryProperties | Record<string, unknown> | undefined,
	options: { maxBytes?: number } = {},
): SanitizedTelemetryProperties {
	const state: SanitizeState = {
		redactionCount: 0,
		payloadTruncated: false,
		maxDepth: 6,
		maxArrayItems: 100,
		maxObjectEntries: 120,
	};
	const value = sanitizeObject((input ?? {}) as Record<string, unknown>, state, 0);
	let properties =
		value && !Array.isArray(value) && typeof value === "object"
			? (value as TelemetryProperties)
			: {};
	let byteLength = encodedByteLength(JSON.stringify(properties));
	const maxBytes = options.maxBytes ?? TELEMETRY_DEFAULT_MAX_EVENT_BYTES;

	if (byteLength > maxBytes) {
		state.payloadTruncated = true;
		properties = {
			_truncated: true,
			_original_bytes: byteLength,
			_original_keys: Object.keys(properties).slice(0, 40),
		};
		byteLength = encodedByteLength(JSON.stringify(properties));
	}

	return {
		properties,
		redactionCount: state.redactionCount,
		payloadTruncated: state.payloadTruncated,
		byteLength,
	};
}

export function createTelemetryClient(
	options: TelemetryClientOptions = {},
): TelemetryClient {
	const disabledByEnv =
		readPublicBoolean("NEXT_PUBLIC_OPENOPPS_ANALYTICS_DISABLED") ||
		readPublicBoolean("NEXT_PUBLIC_OPENOPPS_TELEMETRY_DISABLED");
	const enabled =
		!disabledByEnv &&
		(options.enabled ?? readPublicBoolean("NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED"));
	const endpoint =
		options.endpoint ??
		readPublicString("NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENDPOINT") ??
		TELEMETRY_DEFAULT_ENDPOINT;
	const flushIntervalMs =
		options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS;
	const maxQueueSize = options.maxQueueSize ?? DEFAULT_QUEUE_SIZE;
	const batchSize = options.batchSize ?? DEFAULT_BATCH_SIZE;
	const maxEventBytes =
		options.maxEventBytes ?? TELEMETRY_DEFAULT_MAX_EVENT_BYTES;
	const now = options.now ?? (() => new Date());
	const idGenerator = options.idGenerator ?? createTelemetryId;
	const transport = options.transport ?? defaultTelemetryTransport;
	const anonymousId = enabled
		? getOrCreateStorageValue("local", ANONYMOUS_ID_KEY, idGenerator)
		: "noop";
	const sessionId = enabled
		? getOrCreateStorageValue("session", SESSION_ID_KEY, idGenerator)
		: "noop";
	let pageId = idGenerator();
	let routeContext: TelemetryContext = enabled
		? collectBrowserTelemetryContext()
		: {};
	let queue: TelemetryClientEvent[] = [];
	let timer: ReturnType<typeof setTimeout> | undefined;
	let disposed = false;
	let droppedEvents = 0;

	function scheduleFlush() {
		if (!enabled || disposed || timer || flushIntervalMs <= 0) {
			return;
		}
		timer = setTimeout(() => {
			timer = undefined;
			void flush("timer");
		}, flushIntervalMs);
	}

	function track(eventName: string, properties?: Record<string, unknown>) {
		if (!enabled || disposed) {
			return;
		}
		const normalizedEventName = normalizeEventName(eventName);
		if (!isAllowedTelemetryEventName(normalizedEventName)) {
			return;
		}
		const allowedProperties = filterTelemetryPropertiesForEvent(
			normalizedEventName,
			properties,
		);
		const sanitized = sanitizeTelemetryProperties(allowedProperties, {
			maxBytes: maxEventBytes,
		});
		const context = sanitizeTelemetryProperties(filterTelemetryContext(routeContext), {
			maxBytes: Math.min(maxEventBytes, 16 * 1024),
		});
		const eventProperties = { ...sanitized.properties };
		if (droppedEvents > 0) {
			eventProperties._queue_dropped_events = droppedEvents;
			droppedEvents = 0;
		}
		const event: TelemetryClientEvent = {
			schema_version: TELEMETRY_SCHEMA_VERSION,
			event_id: idGenerator(),
			event_name: normalizedEventName,
			sent_at: now().toISOString(),
			anonymous_id: anonymousId,
			session_id: sessionId,
			page_id: pageId,
			context: context.properties as TelemetryContext,
			properties: eventProperties,
			redaction_count: sanitized.redactionCount + context.redactionCount,
			payload_truncated:
				sanitized.payloadTruncated || context.payloadTruncated,
		};
		if (queue.length >= maxQueueSize) {
			queue = queue.slice(queue.length - maxQueueSize + 1);
			droppedEvents += 1;
		}
		queue.push(event);
		scheduleFlush();
	}

	async function flush(reason = "manual") {
		if (!enabled || disposed || queue.length === 0) {
			return;
		}
		if (timer) {
			clearTimeout(timer);
			timer = undefined;
		}
		const batch = queue.splice(0, batchSize);
		try {
			await transport(endpoint, { events: batch, reason });
		} catch {
			const remainingCapacity = Math.max(0, maxQueueSize - queue.length);
			queue = [...batch.slice(-remainingCapacity), ...queue];
		}
		if (queue.length > 0) {
			scheduleFlush();
		}
	}

	function setRouteContext(context: TelemetryContext) {
		if (!enabled || disposed) {
			return;
		}
		pageId = idGenerator();
		routeContext = {
			...collectBrowserTelemetryContext(),
			...context,
		};
	}

	function dispose() {
		disposed = true;
		if (timer) {
			clearTimeout(timer);
			timer = undefined;
		}
		queue = [];
	}

	return {
		track,
		flush,
		pendingCount: () => queue.length,
		setRouteContext,
		dispose,
	};
}

export function getTelemetryClient(): TelemetryClient {
	defaultClient ??= createTelemetryClient();
	return defaultClient;
}

export function resetTelemetryClientForTests() {
	defaultClient?.dispose();
	defaultClient = undefined;
}

export function trackTelemetry(
	eventName: TelemetryEventName,
	properties?: Record<string, unknown>,
) {
	getTelemetryClient().track(eventName, properties);
}

export function flushTelemetry(reason?: string) {
	return getTelemetryClient().flush(reason);
}

export function setTelemetryRouteContext(context: TelemetryContext) {
	getTelemetryClient().setRouteContext(context);
}

export function isAllowedTelemetryEventName(
	eventName: unknown,
): eventName is TelemetryEventName {
	return Boolean(normalizeTelemetryEventName(eventName));
}

export function normalizeTelemetryEventName(
	eventName: unknown,
): TelemetryEventName | undefined {
	if (typeof eventName !== "string") {
		return undefined;
	}
	const normalized = normalizeEventName(eventName);
	return normalized in TELEMETRY_EVENT_PROPERTY_ALLOWLIST
		? (normalized as TelemetryEventName)
		: undefined;
}

export function filterTelemetryPropertiesForEvent(
	eventName: TelemetryEventName,
	properties: Record<string, unknown> | undefined,
) {
	const allowedKeys = TELEMETRY_EVENT_PROPERTY_ALLOWLIST[eventName];
	if (!properties || allowedKeys.length === 0) {
		return {};
	}
	return Object.fromEntries(
		allowedKeys
			.filter((key) => Object.prototype.hasOwnProperty.call(properties, key))
			.map((key) => [key, properties[key]]),
	);
}

export function filterTelemetryContext(
	context: TelemetryContext | Record<string, unknown> | undefined,
) {
	if (!context) {
		return {};
	}
	return Object.fromEntries(
		Object.entries(context).filter(([key]) =>
			TELEMETRY_CONTEXT_ALLOWLIST.has(key),
		),
	);
}

export function installTelemetryLifecycleHandlers(client = getTelemetryClient()) {
	if (typeof window === "undefined" || typeof document === "undefined") {
		return () => {};
	}
	const flush = (reason: string) => {
		void client.flush(reason);
	};
	const onVisibilityChange = () => {
		if (document.visibilityState === "hidden") {
			flush("visibility_hidden");
		}
	};
	const onPageHide = () => flush("pagehide");
	document.addEventListener("visibilitychange", onVisibilityChange);
	window.addEventListener("pagehide", onPageHide);
	return () => {
		document.removeEventListener("visibilitychange", onVisibilityChange);
		window.removeEventListener("pagehide", onPageHide);
	};
}

export function collectBrowserTelemetryContext(): TelemetryContext {
	if (typeof window === "undefined" || typeof navigator === "undefined") {
		return {};
	}
	const nav = navigator as Navigator & {
		connection?: {
			downlink?: number;
			effectiveType?: string;
			rtt?: number;
			saveData?: boolean;
		};
	};
	return {
		path: window.location.pathname,
		title: document.title || undefined,
		viewport: {
			width: window.innerWidth,
			height: window.innerHeight,
		},
		screen:
			typeof window.screen === "object"
				? {
						width: window.screen.width,
						height: window.screen.height,
						pixelRatio: window.devicePixelRatio || 1,
					}
				: undefined,
		timezone: safeTimezone(),
		language: nav.language,
		languages: Array.from(nav.languages ?? []),
		userAgent: nav.userAgent,
		connection: nav.connection
			? {
					downlink: nav.connection.downlink ?? null,
					effectiveType: nav.connection.effectiveType ?? null,
					rtt: nav.connection.rtt ?? null,
					saveData: nav.connection.saveData ?? null,
				}
			: undefined,
	};
}

async function defaultTelemetryTransport(
	endpoint: string,
	payload: TelemetryRequestPayload,
) {
	const body = JSON.stringify(payload);
	if (
		typeof navigator !== "undefined" &&
		typeof navigator.sendBeacon === "function"
	) {
		const beaconBody =
			typeof Blob === "function"
				? new Blob([body], { type: "application/json" })
				: body;
		if (navigator.sendBeacon(endpoint, beaconBody)) {
			return;
		}
	}
	if (typeof fetch !== "function") {
		return;
	}
	const response = await fetch(endpoint, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body,
		keepalive: true,
	});
	if (!response.ok) {
		throw new Error(`Telemetry request failed: ${response.status}`);
	}
}

function sanitizeObject(
	input: Record<string, unknown>,
	state: SanitizeState,
	depth: number,
): TelemetryValue {
	if (depth > state.maxDepth) {
		state.payloadTruncated = true;
		return "[TRUNCATED]";
	}
	const entries = Object.entries(input);
	const output: TelemetryProperties = {};
	for (const [index, [key, value]] of entries.entries()) {
		if (index >= state.maxObjectEntries) {
			state.payloadTruncated = true;
			break;
		}
		const sanitized = sanitizeValue(value, key, state, depth + 1);
		if (sanitized !== undefined) {
			output[key] = sanitized;
		}
	}
	return output;
}

function sanitizeValue(
	value: unknown,
	key: string,
	state: SanitizeState,
	depth: number,
): TelemetryValue | undefined {
	if (SECRET_KEY_PATTERN.test(key)) {
		state.redactionCount += 1;
		return "[REDACTED]";
	}
	if (value === null) {
		return null;
	}
	if (typeof value === "string") {
		return sanitizeString(value, state);
	}
	if (typeof value === "number") {
		return Number.isFinite(value) ? value : String(value);
	}
	if (typeof value === "boolean") {
		return value;
	}
	if (value instanceof Date) {
		return value.toISOString();
	}
	if (Array.isArray(value)) {
		if (depth > state.maxDepth) {
			state.payloadTruncated = true;
			return "[TRUNCATED]";
		}
		const items = value.slice(0, state.maxArrayItems);
		if (items.length < value.length) {
			state.payloadTruncated = true;
		}
		return items
			.map((item) => sanitizeValue(item, key, state, depth + 1))
			.filter((item): item is TelemetryValue => item !== undefined);
	}
	if (typeof value === "object") {
		if (depth > state.maxDepth) {
			state.payloadTruncated = true;
			return "[TRUNCATED]";
		}
		return sanitizeObject(value as Record<string, unknown>, state, depth + 1);
	}
	return undefined;
}

function sanitizeString(value: string, state: SanitizeState) {
	const url = sanitizeUrl(value, state);
	const sanitized = url ?? value;
	if (SECRET_VALUE_PATTERNS.some((pattern) => pattern.test(sanitized))) {
		state.redactionCount += 1;
		return "[REDACTED]";
	}
	return sanitized;
}

function sanitizeUrl(value: string, state: SanitizeState) {
	const looksLikeUrl =
		value.startsWith("http://") ||
		value.startsWith("https://") ||
		value.startsWith("/") ||
		value.startsWith("?");
	if (!looksLikeUrl) {
		return undefined;
	}
	try {
		const relative = value.startsWith("/") || value.startsWith("?");
		const parsed = new URL(value, "https://openopps.local");
		for (const key of Array.from(parsed.searchParams.keys())) {
			if (SECRET_KEY_PATTERN.test(key)) {
				parsed.searchParams.set(key, "[REDACTED]");
				state.redactionCount += 1;
			}
		}
		if (relative) {
			return `${parsed.pathname}${parsed.search}${parsed.hash}`;
		}
		return parsed.toString();
	} catch {
		return undefined;
	}
}

function normalizeEventName(eventName: string) {
	const normalized = eventName.trim().replace(/[^A-Za-z0-9_.:-]+/g, "_");
	return normalized.length > 0 ? normalized.slice(0, 120) : "";
}

function readPublicString(name: string) {
	if (typeof process === "undefined") {
		return undefined;
	}
	return process.env?.[name];
}

function readPublicBoolean(name: string) {
	const value = readPublicString(name);
	return value === "1" || value === "true" || value === "yes";
}

function getOrCreateStorageValue(
	storageType: "local" | "session",
	key: string,
	idGenerator: () => string,
) {
	const fallback = idGenerator();
	if (typeof window === "undefined") {
		return fallback;
	}
	try {
		const storage =
			storageType === "local" ? window.localStorage : window.sessionStorage;
		const existing = storage.getItem(key);
		if (existing) {
			return existing;
		}
		storage.setItem(key, fallback);
		return fallback;
	} catch {
		return fallback;
	}
}

function createTelemetryId() {
	if (
		typeof crypto !== "undefined" &&
		typeof crypto.randomUUID === "function"
	) {
		return crypto.randomUUID();
	}
	return `tel_${Date.now().toString(36)}_${Math.random()
		.toString(36)
		.slice(2, 12)}`;
}

function safeTimezone() {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone;
	} catch {
		return undefined;
	}
}

function encodedByteLength(value: string) {
	if (typeof TextEncoder !== "undefined") {
		return new TextEncoder().encode(value).byteLength;
	}
	return value.length;
}
