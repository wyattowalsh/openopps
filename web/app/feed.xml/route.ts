import { shouldNoIndexDeployment } from "@/lib/job-detail-utils";
import { getLatestOpenJobsAtomFeed } from "@/lib/jobs-feed-data";

export const dynamic = "force-dynamic";

export async function GET() {
	if (shouldNoIndexDeployment()) {
		return new Response("Not found.\n", { status: 404 });
	}
	const feed = await getLatestOpenJobsAtomFeed();
	return new Response(feed.body, {
		headers: {
			"Cache-Control": "public, max-age=0, must-revalidate",
			"Content-Type": "application/atom+xml; charset=utf-8",
			"X-Content-Type-Options": "nosniff",
		},
	});
}
