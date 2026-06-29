"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef } from "react";

import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	JOB_ROW_HEIGHT,
	JobsBoardListItem,
} from "@/components/jobs-board/jobs-board-list-item";

type JobsBoardListProps = {
	rows: SearchRow[];
	selectedJobId: string;
	onSelectJob: (jobId: string) => void;
};

export function JobsBoardList({
	rows,
	selectedJobId,
	onSelectJob,
}: JobsBoardListProps) {
	const parentRef = useRef<HTMLDivElement>(null);
	// TanStack Virtual is intentionally used here; React Compiler skips memoization.
	// eslint-disable-next-line react-hooks/incompatible-library -- virtualization requires this API
	const virtualizer = useVirtualizer({
		count: rows.length,
		getScrollElement: () => parentRef.current,
		estimateSize: () => JOB_ROW_HEIGHT,
		overscan: 12,
	});

	return (
		<div
			ref={parentRef}
			className="openopps-data-table-wrap h-full min-h-[24rem] overflow-y-auto lg:min-h-[32rem]"
			role="listbox"
			aria-label="Open jobs"
		>
			<div
				className="relative w-full"
				style={{ height: `${virtualizer.getTotalSize()}px` }}
			>
				{virtualizer.getVirtualItems().map((virtualRow) => {
					const row = rows[virtualRow.index];
					return (
						<div
							key={virtualRow.key}
							className="absolute top-0 left-0 w-full"
							style={{
								height: `${virtualRow.size}px`,
								transform: `translateY(${virtualRow.start}px)`,
							}}
						>
							<JobsBoardListItem
								row={row}
								selected={selectedJobId === String(row[0] ?? "")}
								onSelect={onSelectJob}
							/>
						</div>
					);
				})}
			</div>
		</div>
	);
}