import { readFile } from "node:fs/promises";
import path from "node:path";

import {
	parseSnapshotChrome,
	SNAPSHOT_CHROME_PATH,
	type SnapshotChrome,
} from "@/lib/snapshot-chrome";

export async function loadSnapshotChromeFromPublicTree(): Promise<SnapshotChrome | null> {
	const filePath = path.join(
		process.cwd(),
		"public",
		SNAPSHOT_CHROME_PATH.replace(/^\//, ""),
	);
	try {
		const raw = await readFile(filePath, "utf8");
		return parseSnapshotChrome(JSON.parse(raw) as unknown);
	} catch {
		return null;
	}
}
