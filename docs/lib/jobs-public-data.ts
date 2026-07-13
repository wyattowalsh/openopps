import { cache } from "react";

import type { JobDetail } from "@/components/openopps-search/search-types";
import {
	publicJobDetail,
	type JobDetailWithPrivateFields,
} from "@/lib/job-detail-utils";
import { getStaticJobDetail } from "@/lib/jobs-static-data";
import { siteUrl } from "@/lib/shared";

function isPreviewDeployment() {
	return (
		process.env.VERCEL_ENV === "preview" ||
		process.env.NEXT_PUBLIC_VERCEL_ENV === "preview"
	);
}

function isDevelopmentRuntime() {
	return process.env.NODE_ENV === "development";
}

function allowInsecurePublicDataOrigin() {
	return (
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN_ALLOW_INSECURE === "1" ||
		isDevelopmentRuntime() ||
		isPreviewDeployment()
	);
}

function allowedPublicDataHosts(): Set<string> {
	const hosts = new Set<string>();
	try {
		hosts.add(new URL(siteUrl).hostname);
	} catch {
		// siteUrl is a compile-time constant; ignore parse failures.
	}
	const vercelUrl = process.env.VERCEL_URL?.trim();
	if (vercelUrl) {
		try {
			hosts.add(new URL(`https://${vercelUrl.replace(/^https?:\/\//, "")}`).hostname);
		} catch {
			// ignore malformed VERCEL_URL
		}
	}
	const extra = process.env.OPENOPPS_PUBLIC_DATA_ORIGIN_ALLOW_HOSTS?.trim();
	if (extra) {
		for (const host of extra.split(",")) {
			const cleaned = host.trim().toLowerCase();
			if (cleaned) {
				hosts.add(cleaned);
			}
		}
	}
	return hosts;
}

/** Origin used for server-side fetches of committed search artifacts (never request Host). */
export function getAllowlistedPublicSearchOrigin(): URL {
	const configured = process.env.OPENOPPS_PUBLIC_DATA_ORIGIN?.trim();
	if (!configured) {
		return new URL(`${siteUrl}/`);
	}
	const href = configured.endsWith("/") ? configured : `${configured}/`;
	const url = new URL(href);
	const insecureOk = allowInsecurePublicDataOrigin();
	if (url.protocol !== "https:" && !insecureOk) {
		throw new Error(
			"OPENOPPS_PUBLIC_DATA_ORIGIN must use https in production (set OPENOPPS_PUBLIC_DATA_ORIGIN_ALLOW_INSECURE=1 only for explicit overrides)",
		);
	}
	const production = !isDevelopmentRuntime() && !isPreviewDeployment();
	if (production) {
		const host = url.hostname.toLowerCase();
		const allowed = allowedPublicDataHosts();
		if (!allowed.has(host)) {
			throw new Error(
				`OPENOPPS_PUBLIC_DATA_ORIGIN host '${url.hostname}' is not allowlisted for production`,
			);
		}
	}
	return url;
}

export const getPublicJobDetail = cache(
	async (jobId: string, _legacyBaseUrl?: string): Promise<JobDetail | null> => {
		const detail = getStaticJobDetail(jobId);
		return detail ? publicJobDetail(detail as JobDetailWithPrivateFields) : null;
	},
);
