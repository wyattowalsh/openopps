"use client";

import type { ReactNode } from "react";

import type {
	JobLifecycleIndicator,
	JobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	formatDate,
	formatLocations,
	formatSalary,
	J,
	text,
} from "@/components/openopps-search/search-utils";
import { cn } from "@/lib/utils";

export const JOB_ROW_HEIGHT = 68;

type JobsBoardListItemProps = {
	id: string;
	row: SearchRow;
	selected: boolean;
	focused?: boolean;
	posInSet: number;
	setSize: number;
	workflowRecord?: JobWorkflowRecord;
	lifecycleIndicators?: JobLifecycleIndicator[];
	onSelect: (jobId: string) => void;
};

function Chip({ children }: { children: ReactNode }) {
	if (!children) {
		return null;
	}
	return (
		<span className="inline-flex max-w-full items-center truncate rounded-md border border-border/70 bg-background/80 px-1.5 py-0.5 font-mono text-[0.65rem] text-muted-foreground">
			{children}
		</span>
	);
}

export function JobsBoardListItem({
	id,
	row,
	selected,
	focused = false,
	posInSet,
	setSize,
	workflowRecord,
	lifecycleIndicators = [],
	onSelect,
}: JobsBoardListItemProps) {
	const jobId = text(row[J.id]);
	const title = text(row[J.title]) || "Untitled role";
	const company = text(row[J.company]) || text(row[J.board]) || "Unknown company";
	const location = formatLocations(row[J.locations]);
	const remote = text(row[J.remote]);
	const salary = formatSalary(row);
	const team = [text(row[J.department]), text(row[J.team])]
		.filter(Boolean)
		.join(" / ");
	const lineage = [text(row[J.source]), text(row[J.provider])]
		.filter(Boolean)
		.join(" / ");
	const posted = formatDate(row[J.posted]);
	const statusChips = [
		...lifecycleIndicators,
		workflowRecord?.viewedAt ? "viewed" : "",
		workflowRecord?.savedAt ? "saved" : "",
		workflowRecord?.hiddenAt ? "hidden" : "",
		workflowRecord?.appliedAt ? "applied" : "",
		workflowRecord?.notes.trim() ? "notes" : "",
	].filter(Boolean);

	return (
		<div
			id={id}
			role="option"
			tabIndex={-1}
			onClick={() => onSelect(jobId)}
			className={cn(
				"opps-table-row flex w-full cursor-pointer flex-col justify-center gap-1 overflow-hidden px-3 text-left",
			)}
			style={{ height: JOB_ROW_HEIGHT }}
			aria-selected={selected}
			aria-posinset={posInSet}
			aria-setsize={setSize}
			data-job-id={jobId}
			data-selected={selected ? "true" : "false"}
			data-focused={focused ? "true" : "false"}
		>
			<div className="flex min-w-0 items-baseline gap-2">
				<span className="min-w-0 flex-1 truncate font-heading text-sm font-semibold leading-tight">
					{title}
				</span>
				{statusChips.length > 0 ? (
					<span className="hidden shrink-0 gap-1 sm:inline-flex">
						{statusChips.map((chip) => (
							<Chip key={chip}>{chip}</Chip>
						))}
					</span>
				) : null}
				<span className="shrink-0 truncate text-xs text-muted-foreground">
					{company}
				</span>
			</div>
			<div className="flex min-w-0 flex-wrap items-center gap-1.5">
				<Chip>{location || "Location TBD"}</Chip>
				{remote ? <Chip>{remote}</Chip> : null}
				{salary ? <Chip>{salary}</Chip> : null}
				{team ? <Chip>{team}</Chip> : null}
				{lineage ? <Chip>{lineage}</Chip> : null}
				{posted ? <Chip>posted {posted}</Chip> : null}
			</div>
		</div>
	);
}
