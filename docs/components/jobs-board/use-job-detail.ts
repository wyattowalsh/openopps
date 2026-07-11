"use client";

import { useEffect, useState } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { trackTelemetry } from "@/lib/telemetry";

export function useJobDetail(selectedJobId: string | null) {
	const [detail, setDetail] = useState<JobDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState<string | null>(null);

	useEffect(() => {
		if (!selectedJobId) {
			return;
		}

		const jobId = selectedJobId;
		let mounted = true;
		const controller = new AbortController();

		async function loadDetail() {
			setDetailLoading(true);
			setDetailError(null);
			try {
				const response = await fetch(
					`/api/jobs/detail?id=${encodeURIComponent(jobId)}`,
					{
						signal: controller.signal,
						cache: "force-cache",
					},
				);
				if (!response.ok) {
					throw new Error(`Job detail not found (${response.status})`);
				}
				const nextDetail = (await response.json()) as JobDetail;
				if (mounted) {
					setDetail(nextDetail);
					trackTelemetry("jobs.detail_loaded", {
						sourceKeyPresent: Boolean(nextDetail.sourceKey),
						providerIdPresent: Boolean(nextDetail.providerId),
						hasDescription: Boolean(nextDetail.description),
					});
				}
			} catch (caught) {
				if (!mounted || controller.signal.aborted) {
					return;
				}
				const message = formatLoadError(caught);
				setDetail(null);
				setDetailError(message);
				trackTelemetry("jobs.detail_error", {
					hasSelectedJob: Boolean(jobId),
					message,
				});
			} finally {
				if (mounted) {
					setDetailLoading(false);
				}
			}
		}

		void loadDetail();
		return () => {
			mounted = false;
			controller.abort();
		};
	}, [selectedJobId]);

	return { detail, detailLoading, detailError };
}