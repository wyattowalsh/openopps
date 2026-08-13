import path from "node:path";
import { readFile } from "node:fs/promises";

import {
	OpenOppsSnapshotClient,
	type SnapshotClientOptions,
} from "@/lib/openopps-snapshot-client";
import {
	getAllowlistedPublicSearchOrigin,
	getConfiguredPublicDataChannel,
	hasConfiguredPublicDataOrigin,
} from "@/lib/jobs-public-origin";

const PUBLIC_SEARCH_ROOT = "/data/openopps-search/";

export function createServerSnapshotClient(
	options: Omit<SnapshotClientOptions, "legacyFileReader"> & {
		allowLegacyFilesystem?: boolean;
	},
) {
	return new OpenOppsSnapshotClient({
		...options,
		legacyFileReader: options.allowLegacyFilesystem
			? readLegacyPublicFile
			: undefined,
	});
}

/**
 * Use one explicit precedence rule everywhere:
 * configured remote origin/channel > local legacy v6 filesystem.
 */
export function createPublicDataSnapshotClient() {
	const channel = getConfiguredPublicDataChannel();
	const remoteConfigured = hasConfiguredPublicDataOrigin() || channel !== null;
	return createServerSnapshotClient({
		baseUrl: getAllowlistedPublicSearchOrigin(),
		channel,
		allowLegacyFilesystem: !remoteConfigured,
	});
}

async function readLegacyPublicFile(publicPath: string, signal?: AbortSignal) {
	if (!publicPath.startsWith(PUBLIC_SEARCH_ROOT)) {
		throw new Error("legacy public-data read escaped the search root");
	}
	if (signal?.aborted) {
		throw new DOMException("The operation was aborted.", "AbortError");
	}
	const relative = publicPath.slice(1);
	const filePath = path.join(process.cwd(), "public", relative);
	const raw = await readFile(filePath, "utf8");
	if (signal?.aborted) {
		throw new DOMException("The operation was aborted.", "AbortError");
	}
	return raw;
}
