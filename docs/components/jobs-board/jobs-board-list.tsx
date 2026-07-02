"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useRef, useState } from "react";

import {
	clampListFocusIndex,
	isListFocusKey,
	resolveListFocusIndex,
} from "@/components/openopps-search/list-focus";
import type {
	JobLifecycleIndicator,
	JobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	JOB_ROW_HEIGHT,
	JobsBoardListItem,
} from "@/components/jobs-board/jobs-board-list-item";
import { J, text } from "@/components/openopps-search/search-utils";

type JobsBoardListProps = {
	rows: SearchRow[];
	selectedJobId: string;
	jobRecords?: Record<string, JobWorkflowRecord>;
	jobLifecycleIndicators?: Record<string, JobLifecycleIndicator[]>;
	onSelectJob: (jobId: string) => void;
};

export function JobsBoardList({
	rows,
	selectedJobId,
	jobRecords = {},
	jobLifecycleIndicators = {},
	onSelectJob,
}: JobsBoardListProps) {
	const parentRef = useRef<HTMLDivElement>(null);
	const [focusedIndex, setFocusedIndex] = useState(-1);
	const activeFocusedIndex = clampListFocusIndex(focusedIndex, rows.length);
	// TanStack Virtual is intentionally used here; React Compiler skips memoization.
	// eslint-disable-next-line react-hooks/incompatible-library -- virtualization requires this API
	const virtualizer = useVirtualizer({
		count: rows.length,
		getScrollElement: () => parentRef.current,
		estimateSize: () => JOB_ROW_HEIGHT,
		overscan: 12,
	});

	useEffect(() => {
		if (!selectedJobId) {
			return;
		}
		const index = rows.findIndex((row) => text(row[J.id]) === selectedJobId);
		if (index >= 0) {
			setFocusedIndex(index);
		}
	}, [rows, selectedJobId]);

	const handleKeyDown = useCallback(
		(event: React.KeyboardEvent<HTMLDivElement>) => {
			if (rows.length === 0) {
				return;
			}
			if (event.key === "Enter" && activeFocusedIndex >= 0) {
				event.preventDefault();
				const jobId = text(rows[activeFocusedIndex]?.[J.id]);
				if (jobId) {
					onSelectJob(jobId);
				}
				return;
			}
			if (!isListFocusKey(event.key)) {
				return;
			}
			event.preventDefault();
			const nextIndex = resolveListFocusIndex(
				activeFocusedIndex,
				rows.length,
				event.key,
			);
			setFocusedIndex(nextIndex);
			virtualizer.scrollToIndex(nextIndex, { align: "auto" });
		},
		[activeFocusedIndex, onSelectJob, rows, virtualizer],
	);

	return (
		<div
			ref={parentRef}
			className="openopps-data-table-wrap h-full min-h-[24rem] overflow-y-auto lg:min-h-[32rem]"
			role="list"
			aria-label="Open jobs results"
			tabIndex={0}
			onKeyDown={handleKeyDown}
		>
			<div
				className="relative w-full"
				style={{ height: `${virtualizer.getTotalSize()}px` }}
			>
				{virtualizer.getVirtualItems().map((virtualRow) => {
					const row = rows[virtualRow.index];
					const jobId = text(row[J.id]);
					return (
						<div
							key={virtualRow.key}
							className="absolute top-0 left-0 w-full"
							role="listitem"
							style={{
								height: `${virtualRow.size}px`,
								transform: `translateY(${virtualRow.start}px)`,
							}}
						>
							<JobsBoardListItem
								row={row}
								selected={selectedJobId === jobId}
								focused={activeFocusedIndex === virtualRow.index}
								workflowRecord={jobRecords[jobId]}
								lifecycleIndicators={jobLifecycleIndicators[jobId]}
								onSelect={onSelectJob}
							/>
						</div>
					);
				})}
			</div>
		</div>
	);
}
