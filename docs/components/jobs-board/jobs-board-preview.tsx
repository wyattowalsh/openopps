"use client";

import {
	CheckCircle2,
	ExternalLink,
	EyeOff,
	FileJson,
	Loader2,
	StickyNote,
	Bookmark,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type {
	JobLifecycleIndicator,
	JobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import type {
	JobDetail,
	SearchRow,
} from "@/components/openopps-search/search-types";
import {
	formatDate,
	formatLocations,
	formatSalary,
	J,
	parseSourceKeys,
	text,
} from "@/components/openopps-search/search-utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { safeJobExternalUrl } from "@/lib/job-url";
import { sanitizeJobDescriptionHtml } from "@/lib/sanitize-html";
import { trackTelemetry } from "@/lib/telemetry";

type JobsBoardPreviewProps = {
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
	onClose?: () => void;
};

function Field({ label, value }: { label: string; value: ReactNode }) {
	if (
		value === null ||
		value === undefined ||
		value === "" ||
		(Array.isArray(value) && value.length === 0)
	) {
		return null;
	}
	return (
		<div className="grid gap-0.5 text-sm">
			<span className="font-mono text-[0.62rem] font-semibold text-muted-foreground">
				{label}
			</span>
			<span className="min-w-0 break-words text-foreground">{value}</span>
		</div>
	);
}

function lifecycleBadgeVariant(indicator: JobLifecycleIndicator) {
	if (indicator === "new") {
		return "info";
	}
	if (indicator === "changed") {
		return "warning";
	}
	return "muted";
}

function Section({
	title,
	children,
}: {
	title: string;
	children: ReactNode;
}) {
	if (!children) {
		return null;
	}
	return (
		<section className="space-y-2">
			<h3 className="font-mono text-[0.68rem] font-semibold text-muted-foreground">
				{title}
			</h3>
			{children}
		</section>
	);
}

function BulletList({ items }: { items?: string[] }) {
	const values = (items ?? []).map(text).filter(Boolean);
	if (values.length === 0) {
		return null;
	}
	return (
		<ul className="space-y-1.5 rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70 p-3 text-sm leading-6">
			{values.map((item, index) => (
				<li key={`${item}-${index}`} className="flex gap-2">
					<span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
					<span>{item}</span>
				</li>
			))}
		</ul>
	);
}

function JsonBlock({
	label,
	value,
	truncated,
	originalChars,
}: {
	label: string;
	value: unknown;
	truncated?: boolean;
	originalChars?: number;
}) {
	if (!hasStructuredValue(value)) {
		return null;
	}
	return (
		<details className="rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70">
			<summary className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-muted-foreground">
				<span className="inline-flex items-center gap-2">
					<FileJson className="size-3.5" />
					{label}
				</span>
				{truncated ? (
					<Badge variant="warning">
						truncated{originalChars ? ` from ${originalChars} chars` : ""}
					</Badge>
				) : null}
			</summary>
			<pre className="max-h-72 overflow-auto border-t border-border/70 p-3 text-xs leading-5 text-muted-foreground">
				{JSON.stringify(value, null, 2)}
			</pre>
		</details>
	);
}

function hasStructuredValue(value: unknown) {
	if (!value || typeof value !== "object") {
		return false;
	}
	return Array.isArray(value)
		? value.length > 0
		: Object.keys(value as Record<string, unknown>).length > 0;
}

function formatDetailLocations(row: SearchRow | null, detail: JobDetail | null) {
	if (detail?.locations && detail.locations.length > 0) {
		return detail.locations.map(text).filter(Boolean).join(", ");
	}
	return row ? formatLocations(row[J.locations]) : "";
}

function formatDetailSalary(row: SearchRow | null, detail: JobDetail | null) {
	if (detail?.salary) {
		return detail.salary;
	}
	if (
		detail &&
		(detail.salaryMin !== null ||
			detail.salaryMax !== null ||
			detail.salaryCurrency)
	) {
		const min = detail.salaryMin ?? null;
		const max = detail.salaryMax ?? null;
		const currency = detail.salaryCurrency ?? "USD";
		const formatter = new Intl.NumberFormat("en-US", {
			style: "currency",
			currency,
			maximumFractionDigits: 0,
		});
		if (min !== null && max !== null) {
			return `${formatter.format(min)}-${formatter.format(max)}`;
		}
		if (min !== null) {
			return `${formatter.format(min)}+`;
		}
		if (max !== null) {
			return `Up to ${formatter.format(max)}`;
		}
		return currency;
	}
	return row ? formatSalary(row) : "";
}

function structuredJobDescriptionText(detail: JobDetail | null | undefined) {
	const value = detail?.jobDescription?.description;
	if (typeof value !== "string") {
		return "";
	}
	const raw = text(value);
	if (!raw) {
		return "";
	}
	return /<\/?[A-Za-z][^>]*>/.test(raw) ? stripTags(raw) : raw;
}

function stripTags(value: string) {
	return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function useSanitizedHtml(value: string | null | undefined) {
	const source = value ?? "";
	const [sanitized, setSanitized] = useState({ source: "", html: "" });

	useEffect(() => {
		if (!source) {
			return;
		}
		const timeout = window.setTimeout(() => {
			setSanitized({ source, html: sanitizeJobDescriptionHtml(source) });
		}, 0);
		return () => {
			window.clearTimeout(timeout);
		};
	}, [source]);

	if (!source) {
		return "";
	}
	return sanitized.source === source ? sanitized.html : "";
}

export function JobsBoardPreview({
	row,
	selectedJobId,
	detail,
	loading,
	error,
	workflowRecord,
	lifecycleIndicators = [],
	onToggleSaved,
	onToggleHidden,
	onToggleApplied,
	onNotesChange,
	onClose,
}: JobsBoardPreviewProps) {
	const descriptionHtml = useSanitizedHtml(detail?.descriptionHtml);

	if (!row && !selectedJobId) {
		return (
			<div className="opps-empty h-full min-h-[24rem] text-sm text-muted-foreground lg:min-h-[32rem]">
				Select a job to preview posting details.
			</div>
		);
	}

	const title =
		text(detail?.title) ||
		(row ? text(row[J.title]) || "Untitled role" : `Job ${selectedJobId}`);
	const company =
		text(detail?.company) || (row ? text(row[J.company]) || text(row[J.board]) : "");
	const applyUrl = safeJobExternalUrl(detail?.applyUrl);
	const postingUrl =
		safeJobExternalUrl(detail?.postingUrl) ?? safeJobExternalUrl(row ? text(row[J.url]) : "");
	const descriptionSnippet = row ? text(row[J.descriptionSnippet]) : "";
	const descriptionText =
		text(detail?.description) || structuredJobDescriptionText(detail);
	const sourceKeys = row ? parseSourceKeys(row[J.sourceKeys]) : [];
	const responsibilities = (detail?.responsibilities ?? []).map(text).filter(Boolean);
	const qualifications = (detail?.qualifications ?? []).map(text).filter(Boolean);
	const hasDescription =
		Boolean(descriptionSnippet) ||
		Boolean(descriptionHtml) ||
		Boolean(descriptionText) ||
		loading;

	const trackOutbound = (kind: "apply" | "posting", url: string) => {
		trackTelemetry("jobs.outbound_clicked", {
			kind,
			hasUrl: Boolean(url),
			sourceKeyPresent: Boolean(
				detail?.sourceKey ?? (row ? text(row[J.source]) : undefined),
			),
			providerIdPresent: Boolean(
				detail?.providerId ?? (row ? text(row[J.provider]) : undefined),
			),
		});
	};
	const notes = workflowRecord?.notes ?? "";

	return (
		<article className="opps-result-card flex h-full min-h-[24rem] flex-col overflow-hidden p-0 lg:min-h-[32rem]">
			<div className="border-b border-border/70 p-4">
				<div className="flex flex-wrap items-center gap-2">
					<Badge variant="success">
						{text(detail?.status) || (row ? text(row[J.status]) : "selected")}
					</Badge>
					{lifecycleIndicators.map((indicator) => (
						<Badge key={indicator} variant={lifecycleBadgeVariant(indicator)}>
							{indicator}
						</Badge>
					))}
					{workflowRecord?.viewedAt ? <Badge variant="muted">viewed</Badge> : null}
					{workflowRecord?.savedAt ? <Badge variant="default">saved</Badge> : null}
					{workflowRecord?.hiddenAt ? <Badge variant="warning">hidden</Badge> : null}
					{workflowRecord?.appliedAt ? <Badge variant="success">applied</Badge> : null}
					{notes.trim() ? <Badge variant="info">notes</Badge> : null}
					{row ? (
						<span className="font-mono text-xs text-muted-foreground">
							{text(row[J.provider])} / {text(row[J.source])}
						</span>
					) : null}
				</div>
				<h2 className="mt-3 break-words font-heading text-xl font-semibold leading-snug">
					{title}
				</h2>
				{company ? (
					<p className="mt-1 text-sm text-muted-foreground">{company}</p>
				) : null}
				<div className="mt-4 flex flex-wrap gap-2">
					{applyUrl ? (
						<Button asChild size="sm">
							<a
								href={applyUrl}
								target="_blank"
								rel="noopener noreferrer"
								onClick={() => trackOutbound("apply", applyUrl)}
							>
								Apply
								<ExternalLink className="size-3.5" />
							</a>
						</Button>
					) : null}
					{postingUrl ? (
						<Button asChild variant="outline" size="sm">
							<a
								href={postingUrl}
								target="_blank"
								rel="noopener noreferrer"
								onClick={() => trackOutbound("posting", postingUrl)}
							>
								Posting
								<ExternalLink className="size-3.5" />
							</a>
						</Button>
					) : null}
					{onToggleSaved ? (
						<Button
							type="button"
							variant={workflowRecord?.savedAt ? "secondary" : "outline"}
							size="sm"
							aria-pressed={Boolean(workflowRecord?.savedAt)}
							onClick={onToggleSaved}
						>
							<Bookmark className="size-3.5" />
							{workflowRecord?.savedAt ? "Saved" : "Save"}
						</Button>
					) : null}
					{onToggleHidden ? (
						<Button
							type="button"
							variant={workflowRecord?.hiddenAt ? "secondary" : "outline"}
							size="sm"
							aria-pressed={Boolean(workflowRecord?.hiddenAt)}
							onClick={onToggleHidden}
						>
							<EyeOff className="size-3.5" />
							{workflowRecord?.hiddenAt ? "Hidden" : "Hide"}
						</Button>
					) : null}
					{onToggleApplied ? (
						<Button
							type="button"
							variant={workflowRecord?.appliedAt ? "secondary" : "outline"}
							size="sm"
							aria-pressed={Boolean(workflowRecord?.appliedAt)}
							onClick={onToggleApplied}
						>
							<CheckCircle2 className="size-3.5" />
							{workflowRecord?.appliedAt ? "Applied" : "Mark applied"}
						</Button>
					) : null}
					{onClose ? (
						<Button
							type="button"
							variant="ghost"
							size="sm"
							aria-label="Close job preview"
							onClick={onClose}
						>
							Close
						</Button>
					) : null}
				</div>
			</div>

			<div className="flex-1 space-y-4 overflow-y-auto p-4">
				{onNotesChange ? (
					<Section title="Local notes">
						<label className="grid gap-2">
							<span className="sr-only">Local notes</span>
							<textarea
								className="opps-input min-h-24 text-sm leading-6"
								value={notes}
								onChange={(event) => onNotesChange(event.target.value)}
								placeholder="Private note for this browser"
								spellCheck={false}
							/>
							<span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
								<StickyNote className="size-3.5" />
								Notes are excluded from URLs, metadata, and analytics.
							</span>
						</label>
					</Section>
				) : null}

				<div className="grid gap-3 sm:grid-cols-2">
					<Field label="Location" value={formatDetailLocations(row, detail)} />
					<Field
						label="Workplace"
						value={[
							text(detail?.workplaceType) || (row ? text(row[J.workplace]) : ""),
							text(detail?.remote) || (row ? text(row[J.remote]) : ""),
						]
							.filter(Boolean)
							.join(" / ")}
					/>
					<Field
						label="Employment"
						value={text(detail?.employmentType) || (row ? text(row[J.type]) : "")}
					/>
					<Field label="Salary" value={formatDetailSalary(row, detail)} />
					<Field
						label="Department / team"
						value={[
							text(detail?.department) || (row ? text(row[J.department]) : ""),
							text(detail?.team) || (row ? text(row[J.team]) : ""),
						]
							.filter(Boolean)
							.join(" / ")}
					/>
					<Field
						label="Posted"
						value={formatDate(text(detail?.postedAt) || (row ? text(row[J.posted]) : ""))}
					/>
					<Field
						label="Updated"
						value={formatDate(text(detail?.updatedAt) || text(detail?.versionCreatedAt))}
					/>
					<Field
						label="Observed"
						value={formatDate(
							text(detail?.lastSeenAt) ||
								(row ? text(row[J.latestObserved]) : "") ||
								text(detail?.syncedAt),
						)}
					/>
					<Field
						label="Source / board"
						value={[
							text(detail?.sourceKey) || (row ? text(row[J.source]) : ""),
							text(detail?.boardKey) || (row ? text(row[J.board]) : ""),
						]
							.filter(Boolean)
							.join(" / ")}
					/>
					<Field
						label="Provider"
						value={text(detail?.providerId) || (row ? text(row[J.provider]) : "")}
					/>
					<Field label="Remote id" value={text(detail?.remoteId)} />
					<Field label="Job id" value={text(detail?.id) || selectedJobId || ""} />
				</div>

				{sourceKeys.length > 0 ? (
					<Section title="Source keys">
						<div className="flex flex-wrap gap-1.5">
							{sourceKeys.map((sourceKey) => (
								<Badge key={sourceKey} variant="outline">
									{sourceKey}
								</Badge>
							))}
						</div>
					</Section>
				) : null}

				{descriptionSnippet ? (
					<div className="rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70 p-3 text-sm leading-6 text-muted-foreground">
						{descriptionSnippet}
					</div>
				) : null}

				{loading ? (
					<div className="flex items-center gap-2 text-sm text-muted-foreground">
						<Loader2 className="size-4 animate-spin" />
						Loading full description...
					</div>
				) : null}

				{error ? (
					<p className="text-sm text-destructive">
						{error} Showing index snippet only.
					</p>
				) : null}

				{descriptionHtml ? (
					<Section title="Posting description">
						<div
							className="prose prose-sm max-w-none text-foreground [&_a]:text-primary [&_li]:my-1 [&_p]:my-2 [&_ul]:my-2"
							dangerouslySetInnerHTML={{ __html: descriptionHtml }}
						/>
					</Section>
				) : null}

				{!descriptionHtml && descriptionText ? (
					<Section title="Posting description">
						<p className="whitespace-pre-line text-sm leading-6 text-foreground">
							{descriptionText}
						</p>
					</Section>
				) : null}

				{!hasDescription && !error ? (
					<p className="rounded-[var(--opps-radius-md)] border border-border/70 bg-muted/50 p-3 text-sm leading-6 text-muted-foreground">
						This static snapshot has metadata for the posting, but no full
						description text. Use the posting link to inspect the source role.
					</p>
				) : null}

				{responsibilities.length > 0 ? (
					<Section title="Responsibilities">
						<BulletList items={responsibilities} />
					</Section>
				) : null}
				{qualifications.length > 0 ? (
					<Section title="Qualifications">
						<BulletList items={qualifications} />
					</Section>
				) : null}

				{detail?.skills && detail.skills.length > 0 ? (
					<Section title="Skills">
						<div className="flex flex-wrap gap-1.5">
							{detail.skills.map((skill, index) => (
								<Badge
									key={`${skill.name ?? "skill"}-${index}`}
									variant="outline"
									title={skill.keywords?.join(", ")}
								>
									{skill.name ?? "Skill"}
									{skill.level ? ` / ${skill.level}` : ""}
								</Badge>
							))}
						</div>
					</Section>
				) : null}

				<div className="grid gap-3">
					<JsonBlock label="Job description" value={detail?.jobDescription} />
					<JsonBlock label="Compensation" value={detail?.compensation} />
					<JsonBlock label="Job extra payload" value={detail?.jobExtra} />
					<JsonBlock label="Version extra payload" value={detail?.versionExtra} />
					{detail?.payloadSnapshots && detail.payloadSnapshots.length > 0
						? detail.payloadSnapshots.map((snapshot, index) => (
								<JsonBlock
									key={`${snapshot.kind ?? "snapshot"}-${index}`}
									label={`Payload snapshot${snapshot.kind ? `: ${snapshot.kind}` : ""}`}
									value={{
										kind: snapshot.kind,
										payloadHash: snapshot.payloadHash,
										observedAt: snapshot.observedAt,
										payload: snapshot.payload,
									}}
									truncated={snapshot.truncated}
									originalChars={snapshot.originalChars}
								/>
							))
						: null}
				</div>

				<div className="grid gap-3 border-t border-border/70 pt-4 sm:grid-cols-2">
					<Field label="First seen" value={formatDate(text(detail?.firstSeenAt))} />
					<Field label="Last seen" value={formatDate(text(detail?.lastSeenAt))} />
					<Field label="Closed" value={formatDate(text(detail?.closedAt))} />
					<Field label="Synced" value={formatDate(text(detail?.syncedAt))} />
					<Field
						label="Version"
						value={
							detail?.version === null || detail?.version === undefined
								? ""
								: String(detail.version)
						}
					/>
					<Field label="Content hash" value={text(detail?.contentHash)} />
					<Field label="Payload hash" value={text(detail?.payloadHash)} />
				</div>
			</div>
		</article>
	);
}
