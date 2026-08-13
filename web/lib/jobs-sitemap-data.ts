import type { MetadataRoute } from "next";
import { cache } from "react";

import {
	canonicalJobUrl,
	dateOrUndefined,
	shouldNoIndexDeployment,
} from "@/lib/job-detail-utils";
import { createPublicDataSnapshotClient } from "@/lib/openopps-snapshot-client.server";

export { shouldNoIndexDeployment } from "@/lib/job-detail-utils";

export const JOB_SITEMAP_PAGE_SIZE = 45_000;

const getSnapshotClient = cache(() => createPublicDataSnapshotClient());

export async function getSitemapSearchManifest() {
	return getSnapshotClient().getSearchManifest();
}

export async function getJobSitemapCount() {
	return Math.ceil(
		(await getSnapshotClient().getIndexableJobIds()).length /
			JOB_SITEMAP_PAGE_SIZE,
	);
}

export async function getJobSitemapUrls(id: number): Promise<MetadataRoute.Sitemap> {
	const client = getSnapshotClient();
	const [manifest, indexableIds] = await Promise.all([
		client.getSearchManifest(),
		client.getIndexableJobIds(),
	]);
	const start = id * JOB_SITEMAP_PAGE_SIZE;
	const ids = indexableIds.slice(start, start + JOB_SITEMAP_PAGE_SIZE);
	const lastModified = dateOrUndefined(manifest.snapshotAt);
	return ids.map((jobId) => {
		return {
			url: canonicalJobUrl(jobId),
			lastModified,
			changeFrequency: "daily",
			priority: 0.5,
		};
	});
}

export function clearSitemapDataCachesForTests() {
	// React's request cache has no mutable global cache to clear. Retained as a
	// compatibility hook for existing tests and callers.
}
