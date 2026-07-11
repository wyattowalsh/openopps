import { cache } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import {
	publicJobDetail,
	type JobDetailWithPrivateFields,
} from "@/lib/job-detail-utils";
import { getStaticJobDetail } from "@/lib/jobs-static-data";
import { siteUrl } from "@/lib/shared";

/** Origin used for server-side fetches of committed search artifacts (never request Host). */
export function getAllowlistedPublicSearchOrigin(): URL {
	const configured = process.env.OPENOPPS_PUBLIC_DATA_ORIGIN?.trim();
	if (configured) {
		return new URL(configured.endsWith("/") ? configured : `${configured}/`);
	}
	return new URL(`${siteUrl}/`);
}

export const getPublicJobDetail = cache(
	async (jobId: string, _legacyBaseUrl?: string): Promise<JobDetail | null> => {
		const detail = getStaticJobDetail(jobId);
		return detail ? publicJobDetail(detail as JobDetailWithPrivateFields) : null;
	},
);
