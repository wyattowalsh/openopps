"use client";

import { useRef } from "react";

import { useDialogFocusTrap } from "@/components/jobs-board/dialog-focus";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const JOBS_BOARD_CONFIRM_DIALOG_TITLE_ID = "openopps-jobs-confirm-title";

type JobsBoardConfirmDialogProps = {
	open: boolean;
	title: string;
	description: string;
	confirmLabel?: string;
	cancelLabel?: string;
	destructive?: boolean;
	onConfirm: () => void;
	onCancel: () => void;
};

export function JobsBoardConfirmDialog({
	open,
	title,
	description,
	confirmLabel = "Confirm",
	cancelLabel = "Cancel",
	destructive = false,
	onConfirm,
	onCancel,
}: JobsBoardConfirmDialogProps) {
	const dialogRef = useRef<HTMLDivElement>(null);

	useDialogFocusTrap(open, dialogRef, onCancel);

	if (!open) {
		return null;
	}

	return (
		<div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
			<button
				type="button"
				className="absolute inset-0 bg-background/70 backdrop-blur-sm"
				aria-label="Dismiss confirmation"
				tabIndex={-1}
				onClick={onCancel}
			/>
			<div
				ref={dialogRef}
				role="alertdialog"
				aria-modal="true"
				aria-labelledby={JOBS_BOARD_CONFIRM_DIALOG_TITLE_ID}
				aria-describedby="openopps-jobs-confirm-description"
				tabIndex={-1}
				className={cn(
					"relative z-10 w-full max-w-md rounded-[var(--opps-radius-lg)] border border-border/75 bg-card p-4 shadow-[0_24px_80px_color-mix(in_oklab,var(--foreground)_16%,transparent)]",
					"motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-200",
				)}
			>
				<h2
					id={JOBS_BOARD_CONFIRM_DIALOG_TITLE_ID}
					className="font-heading text-lg font-semibold text-foreground"
				>
					{title}
				</h2>
				<p
					id="openopps-jobs-confirm-description"
					className="mt-2 text-sm leading-6 text-muted-foreground"
				>
					{description}
				</p>
				<div className="mt-4 flex flex-wrap justify-end gap-2">
					<Button type="button" variant="outline" size="sm" onClick={onCancel}>
						{cancelLabel}
					</Button>
					<Button
						type="button"
						variant={destructive ? "destructive" : "default"}
						size="sm"
						onClick={onConfirm}
					>
						{confirmLabel}
					</Button>
				</div>
			</div>
		</div>
	);
}