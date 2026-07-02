import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatDate } from "@/components/openopps-search/search-utils";

import { ExplorerMetric } from "./explorer-shared";

type ExplorerStatusBarProps = {
	manifest: SearchManifest | null;
};

export function ExplorerStatusBar({ manifest }: ExplorerStatusBarProps) {
	return (
		<div className="flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
			<div className="min-w-0">
				<p className="opps-kicker">OpenOppsDB search index</p>
				<h2 className="mt-2 font-heading text-2xl font-semibold leading-tight md:text-3xl">
					Boards, routes, and latest jobs
				</h2>
				<p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
					Static snapshot from{" "}
					<code>{manifest?.source.database ?? "kaggle/openoppsdb.sqlite"}</code>
					{manifest?.snapshotAt ? ` at ${formatDate(manifest.snapshotAt)}` : ""}
					.
				</p>
			</div>
			<div className="grid grid-cols-3 gap-2 sm:min-w-[28rem]">
				<ExplorerMetric label="providers" value={manifest?.entities.providers.count} />
				<ExplorerMetric label="boards" value={manifest?.entities.boards.count} />
				<ExplorerMetric label="jobs" value={manifest?.entities.jobs.count} />
			</div>
		</div>
	);
}
