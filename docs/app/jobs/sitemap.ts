import type { MetadataRoute } from "next";

import {
	getJobSitemapCount,
	getJobSitemapUrls,
	shouldNoIndexDeployment,
} from "@/lib/jobs-static-data";

export function generateSitemaps() {
	if (shouldNoIndexDeployment()) {
		return [];
	}
	return Array.from({ length: getJobSitemapCount() }, (_, id) => ({ id }));
}

export default async function sitemap({
	id,
}: {
	id: number | string | Promise<number | string>;
}): Promise<MetadataRoute.Sitemap> {
	if (shouldNoIndexDeployment()) {
		return [];
	}
	return getJobSitemapUrls(Number(await id));
}
