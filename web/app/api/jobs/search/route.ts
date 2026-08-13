import { NextResponse } from "next/server";

const REMOVAL_MESSAGE =
	"Jobs search moved to the release-pinned browser worker; refresh the application to use the current client.";

/**
 * Fail-closed compatibility endpoint for stale clients.
 *
 * Production must never rebuild or scan the complete public jobs corpus in a
 * request handler. Current clients resolve one immutable snapshot and search
 * it in a dedicated Web Worker instead.
 */
export async function GET() {
	return removedResponse();
}

export async function POST() {
	return removedResponse();
}

function removedResponse() {
	return NextResponse.json(
		{
			error: REMOVAL_MESSAGE,
			code: "browser_worker_required",
		},
		{
			status: 410,
			headers: {
				"Cache-Control": "no-store",
			},
		},
	);
}
