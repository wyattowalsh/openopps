"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { JobsBoardMetrics } from "@/components/jobs-board/jobs-board-metrics";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import { JOB_ROW_HEIGHT } from "@/components/jobs-board/jobs-board-list-item";
import type { SnapshotChrome } from "@/lib/snapshot-chrome";

const JOBS_BOARD_FIRST_PAINT_LIST_MIN_HEIGHT_PX = JOBS_BOARD_PAGE_SIZE * JOB_ROW_HEIGHT;

const JobsBoard = dynamic(
	() =>
		import("@/components/jobs-board/jobs-board").then((module) => ({
			default: module.JobsBoard,
		})),
	{ ssr: false },
);

export function JobsBoardGate({ chrome }: { chrome: SnapshotChrome | null }) {
	const [boardPainted, setBoardPainted] = useState(false);

	return (
		<>
			{boardPainted ? null : <JobsBoardFirstPaint chrome={chrome} />}
			<JobsBoard chrome={chrome} onPainted={() => setBoardPainted(true)} />
		</>
	);
}

function JobsBoardFirstPaint({ chrome }: { chrome: SnapshotChrome | null }) {
	return (
		<section
			className="not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6"
			aria-busy="true"
		>
			<p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
				Loading open jobs.
			</p>
			<div className="opps-ledger-shell">
				<div className="shrink-0">
					<JobsBoardMetrics
						chrome={chrome}
						manifest={null}
						matchCount={null}
						searchActive={false}
					/>
				</div>
				<div
					className="mt-4 rounded-[var(--opps-radius-xl)] border border-dashed border-border/80 bg-background/60"
					data-jobs-board-list-reserve=""
					style={{ minHeight: JOBS_BOARD_FIRST_PAINT_LIST_MIN_HEIGHT_PX }}
				/>
			</div>
		</section>
	);
}
