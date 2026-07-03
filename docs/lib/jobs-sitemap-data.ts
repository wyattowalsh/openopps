import fs from "node:fs";
import path from "node:path";

import type { MetadataRoute } from "next";

import type { SearchManifest } from "@/components/openopps-search/search-types";
import {
	canonicalJobUrl,
	dateOrUndefined,
	shouldNoIndexDeployment,
} from "@/lib/job-detail-utils";

export { shouldNoIndexDeployment } from "@/lib/job-detail-utils";

export const JOB_SITEMAP_PAGE_SIZE = 45_000;

const SEARCH_MANIFEST_FILE = path.join(
	process.cwd(),
	"public",
	"data",
	"openopps-search",
	"manifest.json",
);
const JOB_INDEXABLE_IDS_FILE = path.join(
	process.cwd(),
	"public",
	"data",
	"openopps-search",
	"jobs-indexable-ids.json",
);

type JobIndexableIdIndex = {
	version?: number;
	count: number;
	ids: string[];
};

let manifestCache: SearchManifest | null = null;
let indexableJobIdsCache: string[] | null = null;

export function getSitemapSearchManifest() {
	if (!manifestCache) {
		manifestCache = readJson<SearchManifest>(SEARCH_MANIFEST_FILE);
	}
	return manifestCache;
}

export function getJobSitemapCount() {
	return Math.ceil(getIndexableJobDetailIds().length / JOB_SITEMAP_PAGE_SIZE);
}

export function getJobSitemapUrls(id: number): MetadataRoute.Sitemap {
	const manifest = getSitemapSearchManifest();
	const start = id * JOB_SITEMAP_PAGE_SIZE;
	const ids = getIndexableJobDetailIds().slice(start, start + JOB_SITEMAP_PAGE_SIZE);
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
	manifestCache = null;
	indexableJobIdsCache = null;
}

function getIndexableJobDetailIds() {
	if (!indexableJobIdsCache) {
		indexableJobIdsCache = readPrecomputedIndexableJobIds();
	}
	return indexableJobIdsCache;
}

function readPrecomputedIndexableJobIds() {
	if (!fs.existsSync(JOB_INDEXABLE_IDS_FILE)) {
		return [];
	}
	const index = readJson<JobIndexableIdIndex>(JOB_INDEXABLE_IDS_FILE);
	if (index.count !== index.ids.length) {
		return [];
	}
	return index.ids;
}

function readJson<T>(file: string): T {
	return JSON.parse(fs.readFileSync(file, "utf8")) as T;
}
