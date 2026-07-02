"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

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

const FOCUSABLE_SELECTOR = [
	"a[href]",
	"button:not([disabled])",
	"textarea:not([disabled])",
	"input:not([disabled])",
	"select:not([disabled])",
	'[tabindex]:not([tabindex="-1"])',
].join(",");

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
	return key === "Escape";
}

type FocusMove = "dialog" | "first" | "last" | "none";

export function resolvePreviewSheetTabMove({
	activeIndex,
	focusableCount,
	shiftKey,
}: {
	activeIndex: number;
	focusableCount: number;
	shiftKey: boolean;
}): FocusMove {
	if (focusableCount <= 0) {
		return "dialog";
	}
	if (activeIndex < 0) {
		return shiftKey ? "last" : "first";
	}
	if (shiftKey && activeIndex === 0) {
		return "last";
	}
	if (!shiftKey && activeIndex === focusableCount - 1) {
		return "first";
	}
	return "none";
}

function getFocusableElements(root: HTMLElement) {
	return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
		(element) =>
			element.tabIndex >= 0 &&
			!element.hidden &&
			element.getAttribute("aria-hidden") !== "true",
	);
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
	const onCloseRef = useRef(onClose);

	useEffect(() => {
		onCloseRef.current = onClose;
	}, [onClose]);

	useEffect(() => {
		if (!open || !dialogRef.current) {
			return;
		}
		const dialog = dialogRef.current;
		const previouslyFocused =
			document.activeElement instanceof HTMLElement
				? document.activeElement
				: null;
		const previous = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		const focusFrame = window.requestAnimationFrame(() => {
			const target = getFocusableElements(dialog)[0] ?? dialog;
			target.focus({ preventScroll: true });
		});

		function handleKeyDown(event: KeyboardEvent) {
			if (shouldCloseJobsBoardPreviewSheet(event.key)) {
				event.preventDefault();
				onCloseRef.current();
				return;
			}
			if (event.key !== "Tab") {
				return;
			}
			const focusable = getFocusableElements(dialog);
			const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
			const move = resolvePreviewSheetTabMove({
				activeIndex,
				focusableCount: focusable.length,
				shiftKey: event.shiftKey,
			});
			if (move === "none") {
				return;
			}
			event.preventDefault();
			if (move === "dialog") {
				dialog.focus({ preventScroll: true });
				return;
			}
			const target = move === "first" ? focusable[0] : focusable.at(-1);
			target?.focus({ preventScroll: true });
		}

		document.addEventListener("keydown", handleKeyDown);
		return () => {
			window.cancelAnimationFrame(focusFrame);
			document.removeEventListener("keydown", handleKeyDown);
			document.body.style.overflow = previous;
			previouslyFocused?.focus({ preventScroll: true });
		};
	}, [open]);

	if (!open) {
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
