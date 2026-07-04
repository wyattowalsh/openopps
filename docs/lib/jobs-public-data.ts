import { cache } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import { detailBucket } from "@/components/openopps-search/search-utils";

const SEARCH_DATA_BASE_PATH = "/data/openopps-search";

export const getPublicJobDetail = cache(
	async (jobId: string, baseUrl: string): Promise<JobDetail | null> => {
		let decodedJobId: string;
		try {
			decodedJobId = decodeURIComponent(jobId);
		} catch {
			return null;
		}
		const bucket = detailBucket(decodedJobId);
		const details = await fetchPublicJson<Record<string, JobDetail>>(
			baseUrl,
			`${SEARCH_DATA_BASE_PATH}/jobs-details/${bucket}.json`,
		);
		return details?.[decodedJobId] ?? null;
	},
);

async function fetchPublicJson<T>(baseUrl: string, pathname: string) {
	let url: URL;
	try {
		url = new URL(pathname, baseUrl);
	} catch {
		return null;
	}
	try {
		const response = await fetch(url, {
			cache: "no-store",
		});
		if (!response.ok) {
			return null;
		}
		return (await response.json()) as T;
	} catch {
		return null;
	}
}
