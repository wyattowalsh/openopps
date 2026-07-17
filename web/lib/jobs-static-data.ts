import fs from "node:fs";
import path from "node:path";

import type { MetadataRoute } from "next";

import type {
	JobDetail,
	SearchManifest,
} from "@/components/openopps-search/search-types";
import { detailBucket } from "@/components/openopps-search/search-utils";
import {
	canonicalJobUrl,
	dateOrUndefined,
	isIndexableJobDetail,
} from "@/lib/job-detail-utils";

export {
	canonicalJobUrl,
	cleanText,
	dateOrUndefined,
	formatJobDetailTitle,
	isIndexableJobDetail,
	jobBoardDeepLink,
	jobDescriptionText,
	jobDetailDescriptionText,
	jobPostingJsonLd,
	jobPostingJsonLdEnabled,
	primaryJobExternalUrl,
	safeJobExternalUrl,
	serializeJsonLdScript,
	shouldEmitJobPostingJsonLd,
	shouldNoIndexDeployment,
} from "@/lib/job-detail-utils";

export const JOB_SITEMAP_PAGE_SIZE = 45_000;

const SEARCH_DATA_DIR = path.join(process.cwd(), "public", "data", "openopps-search");
const JOB_DETAIL_DIR = path.join(SEARCH_DATA_DIR, "jobs-details");
const JOB_DETAIL_IDS_FILE = path.join(SEARCH_DATA_DIR, "jobs-detail-ids.json");
const JOB_INDEXABLE_IDS_FILE = path.join(SEARCH_DATA_DIR, "jobs-indexable-ids.json");

type JobDetailIdIndex = {
	version?: number;
	count: number;
	ids: string[];
};

type JobIndexableIdIndex = {
	version?: number;
	count: number;
	ids: string[];
};

let manifestCache: SearchManifest | null = null;
let jobIdsCache: string[] | null = null;
let indexableJobIdsCache: string[] | null = null;
const detailBucketCache = new Map<string, Record<string, JobDetail>>();

export function getStaticSearchManifest() {
	if (!manifestCache) {
		manifestCache = readJson<SearchManifest>(path.join(SEARCH_DATA_DIR, "manifest.json"));
	}
	return manifestCache;
}

export function getStaticJobDetailIds() {
	if (!jobIdsCache) {
		jobIdsCache = readJobDetailIdIndex();
	}
	return jobIdsCache;
}

export function getStaticJobDetail(jobId: string) {
	let decodedJobId: string;
	try {
		decodedJobId = decodeURIComponent(jobId);
	} catch {
		return null;
	}
	const bucket = detailBucket(decodedJobId);
	const bucketDetails = readDetailBucket(bucket);
	if (!bucketDetails) {
		return null;
	}
	return bucketDetails[decodedJobId] ?? null;
}

export function getJobSitemapCount() {
	return Math.ceil(getIndexableJobDetailIds().length / JOB_SITEMAP_PAGE_SIZE);
}

export function getJobSitemapUrls(id: number): MetadataRoute.Sitemap {
	const manifest = getStaticSearchManifest();
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

export function getIndexableJobDetailIds() {
	if (!indexableJobIdsCache) {
		if (getStaticSearchManifest().version >= 4) {
			indexableJobIdsCache = readPrecomputedIndexableJobIds();
		} else if (!staticSnapshotCanContainIndexableJobDetails()) {
			indexableJobIdsCache = [];
		} else {
			indexableJobIdsCache = scanIndexableJobDetailIds();
		}
	}
	return indexableJobIdsCache;
}

export function clearStaticJobDataCachesForTests() {
	manifestCache = null;
	jobIdsCache = null;
	indexableJobIdsCache = null;
	detailBucketCache.clear();
}

function staticSnapshotCanContainIndexableJobDetails() {
	return getStaticSearchManifest().source.tables.includes("job_payload_snapshots");
}

function listDetailShardFiles() {
	return fs
		.readdirSync(JOB_DETAIL_DIR)
		.filter((file) => file.endsWith(".json"))
		.sort()
		.map((file) => path.join(JOB_DETAIL_DIR, file));
}

function readJobDetailIdIndex() {
	if (fs.existsSync(JOB_DETAIL_IDS_FILE)) {
		const index = readJson<JobDetailIdIndex>(JOB_DETAIL_IDS_FILE);
		if (index.count === index.ids.length) {
			return index.ids;
		}
	}
	return listDetailShardFiles().flatMap(readTopLevelObjectKeys);
}

function readPrecomputedIndexableJobIds() {
	if (fs.existsSync(JOB_INDEXABLE_IDS_FILE)) {
		const index = readJson<JobIndexableIdIndex>(JOB_INDEXABLE_IDS_FILE);
		if (index.count === index.ids.length) {
			return index.ids;
		}
	}
	return scanIndexableJobDetailIds();
}

function scanIndexableJobDetailIds() {
	return getStaticJobDetailIds().filter((jobId) => {
		const detail = getStaticJobDetail(jobId);
		return detail ? isIndexableJobDetail(detail) : false;
	});
}

function readTopLevelObjectKeys(file: string) {
	return extractTopLevelObjectKeys(fs.readFileSync(file, "utf8"));
}

function extractTopLevelObjectKeys(json: string) {
	const keys: string[] = [];
	let index = skipWhitespace(json, 0);
	if (json[index] !== "{") {
		return keys;
	}
	index += 1;

	while (index < json.length) {
		index = skipWhitespace(json, index);
		if (json[index] === "}") {
			return keys;
		}
		if (json[index] !== '"') {
			return keys;
		}
		const [key, afterKey] = readJsonString(json, index);
		index = skipWhitespace(json, afterKey);
		if (json[index] !== ":") {
			return keys;
		}
		keys.push(key);
		index = skipJsonValue(json, index + 1);
		index = skipWhitespace(json, index);
		if (json[index] === ",") {
			index += 1;
			continue;
		}
		if (json[index] === "}") {
			return keys;
		}
	}
	return keys;
}

function skipJsonValue(json: string, start: number) {
	let index = skipWhitespace(json, start);
	const first = json[index];
	if (first === '"') {
		return readJsonString(json, index)[1];
	}
	if (first === "{" || first === "[") {
		const stack = [first];
		index += 1;
		while (index < json.length && stack.length > 0) {
			const char = json[index];
			if (char === '"') {
				index = readJsonString(json, index)[1];
				continue;
			}
			if (char === "{" || char === "[") {
				stack.push(char);
			} else if (char === "}" || char === "]") {
				stack.pop();
			}
			index += 1;
		}
		return index;
	}
	while (index < json.length && json[index] !== "," && json[index] !== "}") {
		index += 1;
	}
	return index;
}

function readJsonString(json: string, start: number): [string, number] {
	let index = start + 1;
	while (index < json.length) {
		const char = json[index];
		if (char === "\\") {
			index += 2;
			continue;
		}
		if (char === '"') {
			return [JSON.parse(json.slice(start, index + 1)) as string, index + 1];
		}
		index += 1;
	}
	throw new SyntaxError("Unterminated JSON string");
}

function skipWhitespace(json: string, start: number) {
	let index = start;
	while (/\s/.test(json[index] ?? "")) {
		index += 1;
	}
	return index;
}

function readDetailBucket(bucket: string): Record<string, JobDetail> | null {
	const cached = detailBucketCache.get(bucket);
	if (cached) {
		return cached;
	}
	try {
		const details = readJson<Record<string, JobDetail>>(
			path.join(JOB_DETAIL_DIR, `${bucket}.json`),
		);
		detailBucketCache.set(bucket, details);
		return details;
	} catch (error) {
		if (isMissingOrInvalidShardError(error)) {
			return null;
		}
		throw error;
	}
}

function isMissingOrInvalidShardError(error: unknown) {
	if (!error || typeof error !== "object") {
		return false;
	}
	const code = "code" in error ? error.code : undefined;
	if (code === "ENOENT") {
		return true;
	}
	return error instanceof SyntaxError;
}

function readJson<T>(file: string): T {
	return JSON.parse(fs.readFileSync(file, "utf8")) as T;
}
