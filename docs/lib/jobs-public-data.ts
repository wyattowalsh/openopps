import { cache } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import {
	publicJobDetail,
	type JobDetailWithPrivateFields,
} from "@/lib/job-detail-utils";
import { getAllowlistedPublicSearchOrigin } from "@/lib/jobs-public-origin";
import { getStaticJobDetail } from "@/lib/jobs-static-data";

export { getAllowlistedPublicSearchOrigin };

export const getPublicJobDetail = cache(
	async (jobId: string, _legacyBaseUrl?: string): Promise<JobDetail | null> => {
		const detail = getStaticJobDetail(jobId);
		return detail ? publicJobDetail(detail as JobDetailWithPrivateFields) : null;
	},
);
