"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
	resolveDialogTabMove,
	shouldCloseDialogFromKey,
	useDialogFocusTrap,
	type DialogFocusMove,
} from "@/components/jobs-board/dialog-focus";
import type {
	JobLifecycleIndicator,
	JobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import type { JobDetail, SearchRow } from "@/components/openopps-search/search-types";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type JobsBoardPreviewSheetProps = {
	open: boolean;
	row: SearchRow | null;
	selectedJobId?: string | null;
	detail: JobDetail | null;
	loading: boolean;
	error: string | null;
	workflowRecord?: JobWorkflowRecord | null;
	lifecycleIndicators?: JobLifecycleIndicator[];
	onToggleSaved?: () => void;
	onToggleHidden?: () => void;
	onToggleApplied?: () => void;
	onNotesChange?: (notes: string) => void;
	onClose: () => void;
};

export const JOBS_BOARD_PREVIEW_SHEET_TITLE_ID =
	"openopps-jobs-preview-sheet-title";

export function getJobsBoardPreviewSheetDialogProps() {
	return {
		role: "dialog",
		"aria-modal": true,
		"aria-labelledby": JOBS_BOARD_PREVIEW_SHEET_TITLE_ID,
	} as const;
}

export function shouldCloseJobsBoardPreviewSheet(key: string) {
	return shouldCloseDialogFromKey(key);
}

export function resolvePreviewSheetTabMove({
	activeIndex,
	focusableCount,
	shiftKey,
}: {
	activeIndex: number;
	focusableCount: number;
	shiftKey: boolean;
}): DialogFocusMove {
	return resolveDialogTabMove({ activeIndex, focusableCount, shiftKey });
}

export function JobsBoardPreviewSheet({
	open,
	row,
	selectedJobId,
	detail,
	loading,
	error,
	workflowRecord,
	lifecycleIndicators,
	onToggleSaved,
	onToggleHidden,
	onToggleApplied,
	onNotesChange,
	onClose,
}: JobsBoardPreviewSheetProps) {
	const dialogRef = useRef<HTMLDivElement>(null);
	const isMobileSheet = useMediaQuery("(max-width: 1023px)");
	const sheetOpen = open && isMobileSheet;

	useDialogFocusTrap(sheetOpen, dialogRef, onClose);

	if (!sheetOpen) {
		return null;
	}

	return (
		<div className="fixed inset-0 z-50 lg:hidden">
			<button
				type="button"
				className="absolute inset-0 bg-background/70 backdrop-blur-sm"
				aria-label="Close preview"
				tabIndex={-1}
				onClick={onClose}
			/>
			<div
				ref={dialogRef}
				className={cn(
					"absolute inset-x-0 bottom-0 flex max-h-[88vh] flex-col rounded-t-[1.4rem] border border-border/75 bg-card/95 shadow-[0_-24px_80px_color-mix(in_oklab,var(--foreground)_12%,transparent)]",
					"motion-safe:animate-in motion-safe:slide-in-from-bottom motion-safe:duration-300",
				)}
				tabIndex={-1}
				{...getJobsBoardPreviewSheetDialogProps()}
			>
				<div className="flex items-center justify-end border-b border-border/70 px-3 py-2">
					<h2
						id={JOBS_BOARD_PREVIEW_SHEET_TITLE_ID}
						className="sr-only"
					>
						Job preview
					</h2>
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						onClick={onClose}
						aria-label="Close job preview"
					>
						<X className="size-4" />
					</Button>
				</div>
				<div className="min-h-0 flex-1 overflow-hidden">
					<JobsBoardPreview
						row={row}
						selectedJobId={selectedJobId}
						detail={detail}
						loading={loading}
						error={error}
						workflowRecord={workflowRecord}
						lifecycleIndicators={lifecycleIndicators}
						onToggleSaved={onToggleSaved}
						onToggleHidden={onToggleHidden}
						onToggleApplied={onToggleApplied}
						onNotesChange={onNotesChange}
					/>
				</div>
			</div>
		</div>
	);
}

function useMediaQuery(query: string) {
	const [matches, setMatches] = useState(false);

	useEffect(() => {
		if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
			return;
		}
		const media = window.matchMedia(query);
		const update = () => setMatches(media.matches);
		update();
		media.addEventListener("change", update);
		return () => media.removeEventListener("change", update);
	}, [query]);

	return matches;
}
