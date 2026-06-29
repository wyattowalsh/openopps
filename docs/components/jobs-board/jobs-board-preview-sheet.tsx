"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import type { JobDetail, SearchRow } from "@/components/openopps-search/search-types";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type JobsBoardPreviewSheetProps = {
	open: boolean;
	row: SearchRow | null;
	detail: JobDetail | null;
	loading: boolean;
	error: string | null;
	onClose: () => void;
};

export function JobsBoardPreviewSheet({
	open,
	row,
	detail,
	loading,
	error,
	onClose,
}: JobsBoardPreviewSheetProps) {
	useEffect(() => {
		if (!open) {
			return;
		}
		const previous = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		return () => {
			document.body.style.overflow = previous;
		};
	}, [open]);

	if (!open || !row) {
		return null;
	}

	return (
		<div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
			<button
				type="button"
				className="absolute inset-0 bg-background/70 backdrop-blur-sm"
				aria-label="Close preview"
				onClick={onClose}
			/>
			<div
				className={cn(
					"absolute inset-x-0 bottom-0 flex max-h-[88vh] flex-col rounded-t-[1.4rem] border border-border/75 bg-card/95 shadow-[0_-24px_80px_color-mix(in_oklab,var(--foreground)_12%,transparent)]",
					"animate-in slide-in-from-bottom duration-300",
				)}
			>
				<div className="flex items-center justify-end border-b border-border/70 px-3 py-2">
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
						detail={detail}
						loading={loading}
						error={error}
					/>
				</div>
			</div>
		</div>
	);
}