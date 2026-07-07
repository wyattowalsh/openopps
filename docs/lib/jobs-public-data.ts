import { cache } from "react";

import { detailBucket } from "@/components/openopps-search/search-utils";
import type { JobDetail } from "@/components/openopps-search/search-types";
import {
	publicJobDetail,
	type JobDetailWithPrivateFields,
} from "@/lib/job-detail-utils";

const SEARCH_DATA_BASE_PATH = "/data/openopps-search";

export const getPublicJobDetail = cache(
	async (
		jobId: string,
		baseUrl: string,
	): Promise<JobDetail | null> => {
		let decodedJobId: string;
		try {
			decodedJobId = decodeURIComponent(jobId);
		} catch {
			return null;
		}
		const bucket = detailBucket(decodedJobId);
		const details = await fetchPublicJson<Record<string, JobDetailWithPrivateFields>>(
			baseUrl,
			`${SEARCH_DATA_BASE_PATH}/jobs-details/${bucket}.json`,
		);
		const detail = details?.[decodedJobId];
		return detail ? publicJobDetail(detail) : null;
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
			cache: "force-cache",
			next: { revalidate: 300 },
		});
		if (!response.ok) {
			return null;
		}
		return (await response.json()) as T;
	} catch {
		return null;
	}
}
