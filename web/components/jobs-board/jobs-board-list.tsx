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
import { cn } from "@/lib/utils";

type JobsBoardListProps = {
	rows: SearchRow[];
	selectedJobId: string;
	jobRecords?: Record<string, JobWorkflowRecord>;
	jobLifecycleIndicators?: Record<string, JobLifecycleIndicator[]>;
	onSelectJob: (jobId: string) => void;
	fillHeight?: boolean;
};

export function JobsBoardList({
	rows,
	selectedJobId,
	jobRecords = {},
	jobLifecycleIndicators = {},
	onSelectJob,
	fillHeight = false,
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

	const virtualItems = virtualizer.getVirtualItems();

	const handleKeyDown = useCallback(
		(event: React.KeyboardEvent<HTMLDivElement>) => {
			if (rows.length === 0) {
				return;
			}
			if (
				(event.key === "Enter" || event.key === " ") &&
				activeFocusedIndex >= 0
			) {
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

	const handleMouseDown = useCallback(
		(event: React.MouseEvent<HTMLDivElement>) => {
			if (!(event.target instanceof Element)) {
				return;
			}
			const option = event.target.closest("[role='option']");
			if (!(option instanceof HTMLElement)) {
				return;
			}
			const jobId = option.dataset.jobId?.trim();
			if (!jobId) {
				return;
			}
			event.preventDefault();
			parentRef.current?.focus();
			onSelectJob(jobId);
		},
		[onSelectJob],
	);

	const handleFocus = useCallback(() => {
		if (rows.length === 0 || activeFocusedIndex >= 0) {
			return;
		}
		setFocusedIndex(0);
	}, [activeFocusedIndex, rows.length]);

	const activeDescendant =
		activeFocusedIndex >= 0
			? jobsBoardOptionId(text(rows[activeFocusedIndex]?.[J.id]))
			: undefined;

	return (
		<div
			ref={parentRef}
			className={cn(
				"openopps-data-table-wrap h-full min-h-0 overflow-y-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/40",
				!fillHeight && "min-h-[24rem] lg:min-h-[32rem]",
			)}
			role="listbox"
			aria-label="Open jobs results"
			aria-activedescendant={activeDescendant}
			aria-orientation="vertical"
			tabIndex={0}
			onKeyDown={handleKeyDown}
			onMouseDown={handleMouseDown}
			onFocus={handleFocus}
		>
			<div
				className="relative w-full"
				style={{ height: `${virtualizer.getTotalSize()}px` }}
			>
				{virtualItems.map((virtualRow) => {
					const row = rows[virtualRow.index];
					const jobId = text(row[J.id]);
					return (
						<div
							key={virtualRow.key}
							className="absolute top-0 left-0 min-h-11 w-full"
							role="presentation"
							style={{
								height: `${virtualRow.size}px`,
								transform: `translateY(${virtualRow.start}px)`,
							}}
						>
							<JobsBoardListItem
								id={jobsBoardOptionId(jobId)}
								row={row}
								selected={selectedJobId === jobId}
								focused={activeFocusedIndex === virtualRow.index}
								posInSet={virtualRow.index + 1}
								setSize={rows.length}
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

function jobsBoardOptionId(jobId: string) {
	const safeId = jobId.replace(/[^A-Za-z0-9_-]+/g, "-").slice(0, 120);
	return `openopps-job-option-${safeId || "unknown"}`;
}
