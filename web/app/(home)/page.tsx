import { JobsBoardGate } from "@/app/(home)/jobs-board-gate";
import { homeJsonLd, homePageMetadata, jsonLdScriptProps } from "@/lib/site-metadata";
import { loadSnapshotChromeFromPublicTree } from "@/lib/snapshot-chrome.server";

export const metadata = homePageMetadata();

export default async function HomePage() {
	const chrome = await loadSnapshotChromeFromPublicTree();
	return (
		<>
			<script {...jsonLdScriptProps(homeJsonLd())} />
			<JobsBoardGate chrome={chrome} />
		</>
	);
}
