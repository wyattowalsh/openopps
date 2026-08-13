"use client";

import { Download, Loader2, Settings2, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { useDialogFocusTrap } from "@/components/jobs-board/dialog-focus";
import { JobsBoardConfirmDialog } from "@/components/jobs-board/jobs-board-confirm-dialog";
import type {
	JobsLocalSettings,
	JobsLocalStorageStatus,
	JobsLocalSummary,
	JobsRetentionMonths,
} from "@/components/jobs-board/jobs-board-local-state";
import type { JobsOfflineCacheView } from "@/components/jobs-board/use-jobs-offline-cache";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ClearCategory =
	| "all"
	| "applied"
	| "details"
	| "hidden"
	| "notes"
	| "saved"
	| "savedSearches"
	| "viewed";

type JobsBoardLocalDataPanelProps = {
	open: boolean;
	settings: JobsLocalSettings;
	storageStatus: JobsLocalStorageStatus;
	storageError: string | null;
	summary: JobsLocalSummary;
	offlineCache: JobsOfflineCacheView;
	onClose: () => void;
	onSettingsChange: (patch: Partial<JobsLocalSettings>) => void;
	onClearCategory: (category: ClearCategory) => Promise<void> | void;
	onExport: () => string;
	onImport: (
		raw: string,
		mode: "merge" | "replace",
	) => Promise<{ ok: boolean; errors?: string[] }>;
};

const RETENTION_OPTIONS: Array<{
	value: JobsRetentionMonths;
	label: string;
}> = [
	{ value: 1, label: "1 month" },
	{ value: 3, label: "3 months" },
	{ value: 6, label: "6 months" },
	{ value: 12, label: "12 months" },
	{ value: "forever", label: "Forever" },
];

export function JobsBoardLocalDataPanel({
	open,
	settings,
	storageStatus,
	storageError,
	summary,
	offlineCache,
	onClose,
	onSettingsChange,
	onClearCategory,
	onExport,
	onImport,
}: JobsBoardLocalDataPanelProps) {
	const [exportText, setExportText] = useState("");
	const [importText, setImportText] = useState("");
	const [importMode, setImportMode] = useState<"merge" | "replace">("merge");
	const [replaceConfirmed, setReplaceConfirmed] = useState(false);
	const [importMessage, setImportMessage] = useState<string | null>(null);
	const [pendingClear, setPendingClear] = useState<{
		category: ClearCategory;
		label: string;
	} | null>(null);
	const dialogRef = useRef<HTMLDivElement>(null);

	useDialogFocusTrap(open, dialogRef, onClose);

	if (!open) {
		return null;
	}

	const exportData = () => {
		setExportText(onExport());
	};

	const importData = async () => {
		if (importMode === "replace" && !replaceConfirmed) {
			setImportMessage("Confirm replace before importing.");
			return;
		}
		const result = await onImport(importText, importMode);
		if (result.ok) {
			setImportMessage("Import completed.");
			setImportText("");
			setReplaceConfirmed(false);
			return;
		}
		setImportMessage(result.errors?.join(" ") || "Import failed.");
	};

	const clearCategory = (category: ClearCategory, label: string) => {
		setPendingClear({ category, label });
	};

	const confirmPendingClear = async () => {
		if (!pendingClear) {
			return;
		}
		const { category } = pendingClear;
		setPendingClear(null);
		await onClearCategory(category);
	};

	return (
		<div className="fixed inset-0 z-50">
			<button
				type="button"
				className="absolute inset-0 bg-background/70 backdrop-blur-sm"
				aria-label="Close local data settings"
				tabIndex={-1}
				onClick={onClose}
			/>
			<div
				ref={dialogRef}
				className={cn(
					"absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-border/75 bg-card shadow-[0_24px_80px_color-mix(in_oklab,var(--foreground)_16%,transparent)]",
					"motion-safe:animate-in motion-safe:slide-in-from-right motion-safe:duration-300",
				)}
				role="dialog"
				aria-modal="true"
				aria-labelledby="openopps-local-data-title"
				tabIndex={-1}
			>
				<header className="flex items-start justify-between gap-3 border-b border-border/70 p-4">
					<div>
						<div className="flex items-center gap-2">
							<Settings2 className="size-4 text-primary" />
							<h2
								id="openopps-local-data-title"
								className="font-heading text-lg font-semibold"
							>
								App Settings
							</h2>
						</div>
						<p className="mt-1 text-sm text-muted-foreground">
							Local workflow data stays in this browser.
						</p>
					</div>
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						onClick={onClose}
						aria-label="Close app settings"
					>
						<X className="size-4" />
					</Button>
				</header>

				<div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
					<section className="space-y-3">
						<div className="flex flex-wrap items-center gap-2">
							<Badge variant={storageStatus === "available" ? "success" : "warning"}>
								{storageStatus === "loading" ? (
									<Loader2 className="size-3 animate-spin" />
								) : null}
								{storageStatus}
							</Badge>
							<Badge variant="outline">
								~{Math.ceil(summary.approximateBytes / 1024)} KB local data
							</Badge>
						</div>
						{storageError ? (
							<div
								role="alert"
								className="rounded-[var(--opps-radius-md)] border border-destructive/45 bg-destructive/10 p-3 text-sm text-destructive"
							>
								<p className="font-semibold">Local data was not changed.</p>
								<p className="mt-1">
									{storageError} Check browser storage permissions or free space,
									then retry the action.
								</p>
							</div>
						) : null}
						<div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
							<SummaryCard label="Viewed" value={summary.viewed} />
							<SummaryCard label="Saved" value={summary.saved} />
							<SummaryCard label="Hidden" value={summary.hidden} />
							<SummaryCard label="Applied" value={summary.applied} />
							<SummaryCard label="Notes" value={summary.noted} />
							<SummaryCard label="Searches" value={summary.savedSearches} />
							<SummaryCard label="Details" value={summary.retainedDetails} />
							<SummaryCard label="Stale" value={summary.staleDurableJobs} />
						</div>
					</section>

					<section className="space-y-3 border-t border-border/70 pt-4">
						<div className="flex flex-wrap items-center justify-between gap-2">
							<div>
								<h3 className="font-mono text-xs font-semibold text-muted-foreground">
									Offline search
								</h3>
								<p className="mt-1 text-xs leading-5 text-muted-foreground">
									Off by default. Stores only a verified, release-pinned search and
									metadata projection on this device. Queries, workflow data, and full
									job details are not added to this cache.
								</p>
							</div>
							<Badge
								variant={offlineCache.status === "ready" ? "success" : "outline"}
							>
								{offlineCache.status === "checking" ||
								offlineCache.status === "downloading" ? (
									<Loader2 className="size-3 animate-spin" />
								) : null}
								{offlineCache.status}
							</Badge>
						</div>
						<label className="flex items-start gap-2 text-sm">
							<input
								type="checkbox"
								checked={offlineCache.optedIn}
								disabled={
									offlineCache.status === "checking" ||
									offlineCache.status === "downloading"
								}
								onChange={(event) => {
									void (event.target.checked
										? offlineCache.enable()
										: offlineCache.disable());
								}}
							/>
							<span>Keep verified search data available offline</span>
						</label>
						{offlineCache.progress ? (
							<p className="text-xs text-muted-foreground" aria-live="polite">
								Verified {offlineCache.progress.completedEntries} of{" "}
								{offlineCache.progress.totalEntries} files ({formatBytes(
									offlineCache.progress.completedBytes,
								)} of {formatBytes(offlineCache.progress.totalBytes)}).
							</p>
						) : null}
						{offlineCache.ready ? (
							<p className="text-xs text-muted-foreground">
								Pinned release {offlineCache.ready.releaseId.slice(0, 12)}… ·{" "}
								{offlineCache.ready.entryCount} files ·{" "}
								{formatBytes(offlineCache.ready.totalBytes)}
								{offlineCache.status === "stale"
									? " (a newer online release is available)"
									: ""}
							</p>
						) : null}
						{offlineCache.error ? (
							<div
								role="alert"
								className="rounded-[var(--opps-radius-md)] border border-destructive/45 bg-destructive/10 p-3 text-xs leading-5 text-destructive"
							>
								{offlineCache.error}{" "}
								{offlineCache.ready
									? "The previously verified release remains available."
									: "No offline-ready release was recorded."}
							</div>
						) : null}
						{offlineCache.optedIn &&
						(offlineCache.status === "stale" || offlineCache.status === "error") ? (
							<Button
								type="button"
								variant="outline"
								size="sm"
								onClick={() => void offlineCache.retry()}
							>
								Retry verified download
							</Button>
						) : null}
					</section>

					<section className="space-y-3 border-t border-border/70 pt-4">
						<h3 className="font-mono text-xs font-semibold text-muted-foreground">
							Retention
						</h3>
						<label className="grid gap-1.5 text-sm">
							<span className="font-semibold">Hold stale full details</span>
							<select
								className="opps-input h-8"
								value={String(settings.fullDetailRetentionMonths)}
								onChange={(event) => {
									const value = event.target.value;
									onSettingsChange({
										fullDetailRetentionMonths:
											value === "forever"
												? "forever"
												: (Number(value) as JobsRetentionMonths),
									});
								}}
							>
								{RETENTION_OPTIONS.map((option) => (
									<option key={String(option.value)} value={String(option.value)}>
										{option.label}
									</option>
								))}
							</select>
						</label>
						<label className="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								checked={settings.showHidden}
								onChange={(event) =>
									onSettingsChange({ showHidden: event.target.checked })
								}
							/>
							Show hidden jobs in results
						</label>
						<label className="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								checked={settings.hideViewed}
								onChange={(event) =>
									onSettingsChange({ hideViewed: event.target.checked })
								}
							/>
							Hide viewed jobs in results
						</label>
					</section>

					<section className="space-y-3 border-t border-border/70 pt-4">
						<h3 className="font-mono text-xs font-semibold text-muted-foreground">
							Export / import
						</h3>
						<div className="flex flex-wrap gap-2">
							<Button type="button" variant="outline" size="sm" onClick={exportData}>
								<Download className="size-3.5" />
								Export JSON
							</Button>
							<Button
								type="button"
								variant={importMode === "replace" ? "destructive" : "outline"}
								size="sm"
								onClick={importData}
								disabled={
									!importText.trim() ||
									(importMode === "replace" && !replaceConfirmed)
								}
							>
								<Upload className="size-3.5" />
								{importMode === "replace" ? "Replace Data" : "Import JSON"}
							</Button>
							<select
								className="opps-input h-7 w-auto text-xs"
								value={importMode}
								onChange={(event) => {
									setImportMode(event.target.value === "replace" ? "replace" : "merge");
									setReplaceConfirmed(false);
									setImportMessage(null);
								}}
								aria-label="Import mode"
							>
								<option value="merge">Merge by updated date</option>
								<option value="replace">Replace local data</option>
							</select>
						</div>
						<textarea
							className="opps-input min-h-28 w-full font-mono text-xs"
							value={exportText}
							onChange={(event) => setExportText(event.target.value)}
							placeholder="Exported JSON appears here."
							aria-label="Exported local data JSON"
							spellCheck={false}
						/>
						<textarea
							className="opps-input min-h-28 w-full font-mono text-xs"
							value={importText}
							onChange={(event) => {
								setImportText(event.target.value);
								setReplaceConfirmed(false);
								setImportMessage(null);
							}}
							placeholder="Paste an OpenOpps local data backup to import."
							aria-label="Import local data JSON"
							spellCheck={false}
						/>
						{importMode === "replace" ? (
							<label className="flex items-start gap-2 rounded-[var(--opps-radius-md)] border border-destructive/40 bg-destructive/10 p-2 text-xs leading-5 text-destructive">
								<input
									type="checkbox"
									className="mt-0.5"
									checked={replaceConfirmed}
									onChange={(event) => {
										setReplaceConfirmed(event.target.checked);
										setImportMessage(null);
									}}
								/>
								<span>
									Replace all saved, hidden, viewed, applied, notes, searches, and
									retained detail data in this browser.
								</span>
							</label>
						) : null}
						{importMessage ? (
							<p className="text-sm text-muted-foreground">{importMessage}</p>
						) : null}
					</section>

					<section className="space-y-3 border-t border-border/70 pt-4">
						<h3 className="font-mono text-xs font-semibold text-muted-foreground">
							Clear local data
						</h3>
						<div className="grid gap-2 sm:grid-cols-2">
							<ClearButton label="viewed state" onClick={() => clearCategory("viewed", "viewed state")} />
							<ClearButton label="saved jobs" onClick={() => clearCategory("saved", "saved jobs")} />
							<ClearButton label="hidden jobs" onClick={() => clearCategory("hidden", "hidden jobs")} />
							<ClearButton label="applied flags" onClick={() => clearCategory("applied", "applied flags")} />
							<ClearButton label="notes" onClick={() => clearCategory("notes", "notes")} />
							<ClearButton label="saved searches" onClick={() => clearCategory("savedSearches", "saved searches")} />
							<ClearButton label="retained details" onClick={() => clearCategory("details", "retained details")} />
							<ClearButton label="all local data" destructive onClick={() => clearCategory("all", "all local data")} />
						</div>
					</section>
				</div>
			</div>
			<JobsBoardConfirmDialog
				open={Boolean(pendingClear)}
				title={pendingClear ? `Clear ${pendingClear.label}?` : "Clear local data?"}
				description="This only changes local browser data for OpenOpps on this device."
				confirmLabel="Clear"
				destructive
				onCancel={() => setPendingClear(null)}
				onConfirm={() => {
					void confirmPendingClear();
				}}
			/>
		</div>
	);
}

function formatBytes(bytes: number) {
	if (bytes < 1024 * 1024) {
		return `${Math.ceil(bytes / 1024)} KB`;
	}
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function SummaryCard({ label, value }: { label: string; value: number }) {
	return (
		<div className="rounded-[var(--opps-radius-md)] border border-border/70 bg-background/70 p-3">
			<div className="font-mono text-[0.65rem] font-semibold text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 text-lg font-semibold">{value}</div>
		</div>
	);
}

function ClearButton({
	label,
	destructive = false,
	onClick,
}: {
	label: string;
	destructive?: boolean;
	onClick: () => void;
}) {
	return (
		<Button
			type="button"
			variant={destructive ? "destructive" : "outline"}
			size="sm"
			onClick={onClick}
			className="justify-start"
		>
			<Trash2 className="size-3.5" />
			Clear {label}
		</Button>
	);
}
