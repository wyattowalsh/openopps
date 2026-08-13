import { cache } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import {
	publicJobDetail,
	type JobDetailWithPrivateFields,
} from "@/lib/job-detail-utils";
import { getAllowlistedPublicSearchOrigin } from "@/lib/jobs-public-origin";
import { createPublicDataSnapshotClient } from "@/lib/openopps-snapshot-client.server";

export { getAllowlistedPublicSearchOrigin };

const getSnapshotClient = cache(() => createPublicDataSnapshotClient());

export const getPublicJobDetail = cache(
	async (jobId: string): Promise<JobDetail | null> => {
		const detail = await getSnapshotClient().getJobDetail(jobId);
		return detail ? publicJobDetail(detail as JobDetailWithPrivateFields) : null;
	},
);
