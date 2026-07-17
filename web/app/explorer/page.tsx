import { OpenOppsSearchExplorer } from "@/components/openopps-search-explorer";
import type { Metadata } from "next";

export const metadata: Metadata = {
	title: "Explorer",
	description:
		"Dashboard for OpenOppsDB snapshot coverage, data quality, route health, and row inspection.",
};

export default function ExplorerPage() {
	return <OpenOppsSearchExplorer />;
}
