import { OpenOppsSearchExplorer } from "@/components/openopps-search-explorer";

import {
	explorerJsonLd,
	explorerPageMetadata,
	jsonLdScriptProps,
} from "@/lib/site-metadata";

export const metadata = explorerPageMetadata();

export default function ExplorerPage() {
	return (
		<>
			<script {...jsonLdScriptProps(explorerJsonLd())} />
			<OpenOppsSearchExplorer />
		</>
	);
}
