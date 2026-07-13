import { NextResponse } from "next/server";

import type { JobBoardFilters } from "@/components/jobs-board/jobs-board-filter-engine";
import { getAllowlistedPublicSearchOrigin } from "@/lib/jobs-public-origin";
import {
	normalizeJobsSearchFilters,
	normalizeJobsSearchSortKey,
	normalizeLimit,
	normalizePage,
	normalizePageSize,
	searchPublicJobsIndex,
	summarizePublicJobsIndex,
} from "@/lib/jobs-search-service";

export const dynamic = "force-dynamic";

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
