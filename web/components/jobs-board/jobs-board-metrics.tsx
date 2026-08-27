import { Database, ExternalLink } from "lucide-react";
import Link from "next/link";

import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatCount, formatDate } from "@/components/openopps-search/search-utils";

type JobsBoardMetricsProps = {
	manifest: SearchManifest | null;
	matchCount: number | null;
	searchActive: boolean;
};

function Metric({
	label,
	value,
}: {
	label: string;
	value?: number | string | null;
}) {
	const display =
		value === null ? "—" : typeof value === "string" ? value : formatCount(value);
	return (
		<div className="opps-metric">
			<div className="font-heading text-xl font-semibold text-primary">
				{display}
			</div>
			<div className="mt-1 truncate font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
				{label}
			</div>
		</div>
	);
}

export function JobsBoardMetrics({
	manifest,
	matchCount,
	searchActive,
}: JobsBoardMetricsProps) {
	const totalJobs = manifest?.entities.jobs.count;
	const openJobs = manifest?.openJobCount ?? totalJobs;
	const sourceRows = manifest?.counts?.snapshot?.sourceRows;
	const providerRoutes = manifest?.counts?.snapshot?.providerRoutes;
	const kaggleId = manifest?.kaggleDatasetId ?? "wyattowalsh/openoppsdb";
	const kaggleUrl = `https://www.kaggle.com/datasets/${kaggleId}`;
	const metrics = searchActive
		? [
				{ label: "matches", value: matchCount },
				{ label: "open jobs", value: openJobs },
				{ label: "indexed jobs", value: totalJobs },
				{ label: "routes", value: providerRoutes },
			]
		: [
				{ label: "open jobs", value: openJobs },
				{ label: "indexed jobs", value: totalJobs },
				{ label: "sources", value: sourceRows },
				{ label: "routes", value: providerRoutes },
			];

	return (
		<div className="flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
			<div className="min-w-0">
				<p className="opps-kicker">OpenOpps jobs board</p>
				<h1 className="mt-2 font-heading text-2xl font-semibold leading-tight md:text-3xl">
					Open public opportunities
				</h1>
				<p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
					Static snapshot from{" "}
					<code>{manifest?.source.database ?? "kaggle/openoppsdb.sqlite"}</code>
					{manifest?.snapshotAt ? ` at ${formatDate(manifest.snapshotAt)}` : ""}
					. Open roles only — use the{" "}
					<Link href="/explorer" className="text-primary underline-offset-2 hover:underline">
						dataset explorer
					</Link>{" "}
					for closed postings and provider routes.
				</p>
				<div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
					<Database className="size-4" />
					<span className="openopps-status-chip" data-tone="success">
						open only
					</span>
					<Link
						href={kaggleUrl}
						target="_blank"
						rel="noopener noreferrer"
						className="inline-flex items-center gap-1 text-primary hover:underline"
					>
						Kaggle dataset
						<ExternalLink className="size-3" />
					</Link>
				</div>
			</div>
			<div className="grid grid-cols-2 gap-2 sm:min-w-[30rem] sm:grid-cols-4">
				{metrics.map((metric) => (
					<Metric key={metric.label} label={metric.label} value={metric.value} />
				))}
			</div>
		</div>
	);
}
