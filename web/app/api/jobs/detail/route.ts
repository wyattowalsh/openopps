import { NextResponse } from "next/server";

import { getPublicJobDetail } from "@/lib/jobs-public-data";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
	const url = new URL(request.url);
	const jobId = url.searchParams.get("id")?.trim();
	if (!jobId) {
		return NextResponse.json({ error: "Missing job id." }, { status: 400 });
	}

	const detail = await getPublicJobDetail(jobId);
	if (!detail) {
		return NextResponse.json({ error: "Job detail not found." }, { status: 404 });
	}

	return NextResponse.json(detail, {
		headers: {
			"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
		},
	});
}
