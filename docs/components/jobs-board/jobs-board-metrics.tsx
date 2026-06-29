import { Database, ExternalLink } from "lucide-react";
import Link from "next/link";

import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatCount, formatDate } from "@/components/openopps-search/search-utils";

type JobsBoardMetricsProps = {
	manifest: SearchManifest | null;
	matchCount: number;
};

function Metric({ label, value }: { label: string; value?: number }) {
	return (
		<div className="opps-metric">
			<div className="font-heading text-xl font-semibold text-primary">
				{formatCount(value)}
			</div>
			<div className="mt-1 truncate font-mono text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
				{label}
			</div>
		</div>
	);
}

export function JobsBoardMetrics({
	manifest,
	matchCount,
}: JobsBoardMetricsProps) {
	const totalJobs = manifest?.entities.jobs.count;
	const openJobs = manifest?.openJobCount ?? totalJobs;
	const kaggleId = manifest?.kaggleDatasetId ?? "wyattowalsh/openoppsdb";
	const kaggleUrl = `https://www.kaggle.com/datasets/${kaggleId}`;

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
					<Link href="/docs/explorer" className="text-primary underline-offset-2 hover:underline">
						dataset explorer
					</Link>{" "}
					for closed postings and provider routes.
				</p>
				<div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
					<Database className="size-4" />
					<span className="openopps-status-chip" data-tone="jobs">
						open only
					</span>
					<Link
						href={kaggleUrl}
						target="_blank"
						rel="noreferrer"
						className="inline-flex items-center gap-1 text-primary hover:underline"
					>
						Kaggle dataset
						<ExternalLink className="size-3" />
					</Link>
				</div>
			</div>
			<div className="grid grid-cols-3 gap-2 sm:min-w-[28rem]">
				<Metric label="matches" value={matchCount} />
				<Metric label="open jobs" value={openJobs} />
				<Metric label="indexed jobs" value={totalJobs} />
			</div>
		</div>
	);
}