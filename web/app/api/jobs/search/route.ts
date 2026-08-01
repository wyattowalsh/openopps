import { NextResponse } from "next/server";

import {
	MAX_SAVED_SEARCH_COUNT_BATCH,
	MAX_SAVED_SEARCH_COUNT_BODY_BYTES,
} from "@/app/api/jobs/search/saved-search-limits";
import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { getAllowlistedPublicSearchOrigin } from "@/lib/jobs-public-origin";
import {
	countSavedSearchMatches,
	normalizeJobsSearchFilters,
	normalizeJobsSearchSortKey,
	normalizeLimit,
	normalizePage,
	normalizePageSize,
	searchPublicJobsIndex,
	summarizePublicJobsIndex,
} from "@/lib/jobs-search-service";

export const dynamic = "force-dynamic";

const MAX_SAVED_SEARCH_ID_LENGTH = 128;
const MAX_FILTER_VALUE_LENGTH = 500;
const FILTER_KEYS = new Set(Object.keys(DEFAULT_JOB_BOARD_FILTERS));

function resolveSearchDataOrigin(requestUrl: URL): URL {
	// Explicit env always wins (validated allowlist).
	if (process.env.OPENOPPS_PUBLIC_DATA_ORIGIN?.trim()) {
		return getAllowlistedPublicSearchOrigin();
	}
	// Local next start / Playwright e2e: load static shards from the same host.
	// Prefer 127.0.0.1 over "localhost" so Node server-side fetch does not hit
	// IPv6 ::1 when the Next listener is IPv4-only.
	if (
		requestUrl.hostname === "localhost" ||
		requestUrl.hostname === "127.0.0.1" ||
		requestUrl.hostname === "::1"
	) {
		const port = requestUrl.port ? `:${requestUrl.port}` : "";
		return new URL(`http://127.0.0.1${port}/`);
	}
	return getAllowlistedPublicSearchOrigin();
}

export async function GET(request: Request) {
	const url = new URL(request.url);
	const dataOrigin = resolveSearchDataOrigin(url);
	const filters = filtersFromSearchParams(url.searchParams);
	const sortKey = normalizeJobsSearchSortKey(url.searchParams.get("sort"), filters);
	const signal = request.signal;
	try {
		if (parseBooleanParam(url.searchParams.get("summary"))) {
			const summary = await summarizePublicJobsIndex({
					baseUrl: dataOrigin,
					filters,
					sortKey,
					signal,
			});
			return NextResponse.json(summary, {
				headers: {
					"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
				},
			});
		}
		const result = await searchPublicJobsIndex({
			baseUrl: dataOrigin,
			filters,
			sortKey,
			limit: normalizeLimit(url.searchParams.get("limit")),
			page: normalizePage(url.searchParams.get("page")),
			pageSize: normalizePageSize(
				url.searchParams.get("pageSize") ?? url.searchParams.get("limit"),
			),
			signal,
		});

		return NextResponse.json(result, {
			headers: {
				"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
			},
		});
	} catch (caught) {
		if (
			(caught instanceof DOMException && caught.name === "AbortError") ||
			(caught instanceof Error && caught.name === "AbortError")
		) {
			return new NextResponse(null, { status: 499 });
		}
		throw caught;
	}
}

export async function POST(request: Request) {
	const raw = await request.text();
	if (new TextEncoder().encode(raw).length > MAX_SAVED_SEARCH_COUNT_BODY_BYTES) {
		return validationError("Saved-search count request exceeds 64 KiB.", 413);
	}
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		return validationError("Request body must be valid JSON.");
	}
	const parsed = parseSavedSearchCountRequest(value);
	if (!parsed.ok) {
		return validationError(parsed.error);
	}
	try {
		const requestUrl = new URL(request.url);
		const result = await countSavedSearchMatches({
			baseUrl: resolveSearchDataOrigin(requestUrl),
			searches: parsed.searches,
			signal: request.signal,
		});
		const body = JSON.stringify(result);
		if (new TextEncoder().encode(body).length > MAX_SAVED_SEARCH_COUNT_BODY_BYTES) {
			throw new Error("Saved-search count response exceeded its 64 KiB budget.");
		}
		return new NextResponse(body, {
			headers: {
				"Cache-Control": "private, no-store",
				"Content-Type": "application/json; charset=utf-8",
			},
		});
	} catch (caught) {
		if (
			(caught instanceof DOMException && caught.name === "AbortError") ||
			(caught instanceof Error && caught.name === "AbortError")
		) {
			return new NextResponse(null, { status: 499 });
		}
		throw caught;
	}
}

function parseSavedSearchCountRequest(value: unknown):
	| {
			ok: true;
			searches: Array<{
				id: string;
				filters: JobBoardFilters;
				sortKey: "latest" | "relevance";
				reviewedAt: string;
			}>;
	  }
	| { ok: false; error: string } {
	if (!isPlainObject(value) || !hasOnlyKeys(value, new Set(["searches"]))) {
		return { ok: false, error: "Request body must contain only searches." };
	}
	if (!Array.isArray(value.searches)) {
		return { ok: false, error: "searches must be an array." };
	}
	if (value.searches.length > MAX_SAVED_SEARCH_COUNT_BATCH) {
		return {
			ok: false,
			error: `At most ${MAX_SAVED_SEARCH_COUNT_BATCH} saved searches may be counted at once.`,
		};
	}
	const ids = new Set<string>();
	const searches = [];
	for (const candidate of value.searches) {
		if (
			!isPlainObject(candidate) ||
			!hasOnlyKeys(candidate, new Set(["id", "filters", "sortKey", "reviewedAt"]))
		) {
			return { ok: false, error: "Each saved search contains unsupported fields." };
		}
		const id = typeof candidate.id === "string" ? candidate.id.trim() : "";
		if (!id || id.length > MAX_SAVED_SEARCH_ID_LENGTH || ids.has(id)) {
			return { ok: false, error: "Saved-search ids must be unique and at most 128 characters." };
		}
		if (!isPlainObject(candidate.filters) || !hasOnlyKeys(candidate.filters, FILTER_KEYS)) {
			return { ok: false, error: `Saved search ${id} contains invalid filters.` };
		}
		const partial: Partial<JobBoardFilters> = {};
		for (const [key, filterValue] of Object.entries(candidate.filters)) {
			if (key === "wide" || key === "includeAllIndexed") {
				if (typeof filterValue !== "boolean") {
					return { ok: false, error: `Saved search ${id} contains invalid filters.` };
				}
				(partial as Record<string, unknown>)[key] = filterValue;
			} else {
				if (typeof filterValue !== "string" || filterValue.length > MAX_FILTER_VALUE_LENGTH) {
					return { ok: false, error: `Saved search ${id} contains invalid filters.` };
				}
				(partial as Record<string, unknown>)[key] = filterValue;
			}
		}
		const sortKeyRaw = candidate.sortKey;
		if (sortKeyRaw !== "latest" && sortKeyRaw !== "relevance") {
			return { ok: false, error: `Saved search ${id} contains an invalid sort key.` };
		}
		const sortKey: "latest" | "relevance" = sortKeyRaw;
		const reviewedAt = typeof candidate.reviewedAt === "string" ? candidate.reviewedAt : "";
		if (!reviewedAt || !Number.isFinite(Date.parse(reviewedAt))) {
			return { ok: false, error: `Saved search ${id} contains an invalid review cursor.` };
		}
		ids.add(id);
		searches.push({
			id,
			filters: normalizeJobsSearchFilters(partial),
			sortKey,
			reviewedAt,
		});
	}
	return { ok: true, searches };
}

function validationError(message: string, status = 422) {
	return NextResponse.json({ error: message }, { status });
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, keys: ReadonlySet<string>) {
	return Object.keys(value).every((key) => keys.has(key));
}

function filtersFromSearchParams(params: URLSearchParams): JobBoardFilters {
	return normalizeJobsSearchFilters({
		query: params.get("q") ?? "",
		wide: parseBooleanParam(params.get("wide")),
		includeAllIndexed: parseBooleanParam(params.get("all")),
		source: params.get("source") ?? "",
		provider: params.get("provider") ?? "",
		location: params.get("location") ?? "",
		department: params.get("department") ?? "",
		team: params.get("team") ?? "",
		workplace: params.get("workplace") ?? "",
		remote: params.get("remote") ?? "",
		employment: params.get("employment") ?? "",
		skill: params.get("skill") ?? "",
		salaryMin: params.get("salaryMin") ?? "",
		salaryMax: params.get("salaryMax") ?? "",
		postedAfter: params.get("postedAfter") ?? "",
		postedBefore: params.get("postedBefore") ?? "",
	});
}

function parseBooleanParam(value: string | null) {
	return value === "1" || value === "true";
}
