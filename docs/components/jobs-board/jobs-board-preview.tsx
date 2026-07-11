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
import type { ReactNode } from "react";

import type {
	JobLifecycleIndicator,
	JobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import type {
	JobDetail,
	SearchRow,
} from "@/components/openopps-search/search-types";
import {
	formatCurrencyRange,
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
	/** When false, omit split-pane divider chrome (e.g. mobile sheet). */
	paneChrome?: boolean;
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
		<section className="space-y-2 border-t border-border/70 pt-4">
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
		<ul className="space-y-1.5 text-sm leading-6">
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
		<details className="pt-3 [&+&]:border-t [&+&]:border-border/70">
			<summary className="flex cursor-pointer items-center justify-between gap-3 py-1 text-xs font-semibold text-muted-foreground">
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
			<pre className="mt-2 max-h-72 overflow-auto text-xs leading-5 text-muted-foreground">
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

const PRIMARY_DETAIL_KEYS = new Set([
	"id",
	"status",
	"sourceKey",
	"boardKey",
	"providerId",
	"remoteId",
	"title",
	"company",
	"department",
	"team",
	"workplaceType",
	"remote",
	"employmentType",
	"locations",
	"salaryMin",
	"salaryMax",
	"salaryCurrency",
	"description",
	"descriptionHtml",
	"responsibilities",
	"qualifications",
	"skills",
	"jobDescription",
	"compensation",
	"experience",
	"salary",
	"applyUrl",
	"postingUrl",
	"postedAt",
	"updatedAt",
	"versionCreatedAt",
	"firstSeenAt",
	"lastSeenAt",
	"closedAt",
	"syncedAt",
	"version",
	"contentHash",
	"payloadHash",
	"detailTier",
	"jobExtra",
	"versionExtra",
	"payloadSnapshots",
]);

function additionalPublicFields(detail: JobDetail | null) {
	if (!detail) {
		return {};
	}
	return Object.fromEntries(
		Object.entries(detail).filter(([key, value]) => {
			if (PRIMARY_DETAIL_KEYS.has(key)) {
				return false;
			}
			if (value === null || value === undefined || value === "") {
				return false;
			}
			if (Array.isArray(value) && value.length === 0) {
				return false;
			}
			if (
				typeof value === "object" &&
				!Array.isArray(value) &&
				Object.keys(value).length === 0
			) {
				return false;
			}
			return true;
		}),
	);
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
		return formatCurrencyRange({
			min,
			max,
			currency: detail.salaryCurrency,
		});
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
	paneChrome = true,
}: JobsBoardPreviewProps) {
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
	const descriptionText =
		text(detail?.description) || structuredJobDescriptionText(detail);
	const sourceKeys = row ? parseSourceKeys(row[J.sourceKeys]) : [];
	const responsibilities = (detail?.responsibilities ?? []).map(text).filter(Boolean);
	const qualifications = (detail?.qualifications ?? []).map(text).filter(Boolean);
	const hasDescription = Boolean(descriptionText) || loading;
	const extraPublicFields = additionalPublicFields(detail);
	const hasStructuredPayloadSection =
		hasStructuredValue(extraPublicFields) ||
		hasStructuredValue(detail?.jobDescription) ||
		hasStructuredValue(detail?.compensation) ||
		hasStructuredValue(detail?.jobExtra) ||
		hasStructuredValue(detail?.versionExtra);

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

	const paneChromeClass = paneChrome
		? "lg:border-l lg:border-border/70 lg:pl-4"
		: "";

	return (
		<article
			className={`flex h-full min-h-[24rem] flex-col overflow-hidden lg:min-h-[32rem] ${paneChromeClass}`.trim()}
		>
			<header className="border-b border-border/70 pb-4">
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
			</header>

			<div className="flex-1 overflow-y-auto">
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

				<section className="grid gap-3 border-t border-border/70 pt-4 sm:grid-cols-2">
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
					<Field label="Experience" value={text(detail?.experience)} />
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
					<Field label="Detail tier" value={text(detail?.detailTier)} />
					<Field label="Remote id" value={text(detail?.remoteId)} />
					<Field label="Job id" value={text(detail?.id) || selectedJobId || ""} />
					<Field label="Apply URL" value={applyUrl} />
					<Field label="Posting URL" value={postingUrl} />
				</section>

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

				{loading ? (
					<section className="flex items-center gap-2 border-t border-border/70 pt-4 text-sm text-muted-foreground">
						<Loader2 className="size-4 animate-spin" />
						Loading full description...
					</section>
				) : null}

				{error ? (
					<section className="border-t border-border/70 pt-4">
						<p className="text-sm text-destructive">
							{error} Showing available index metadata only.
						</p>
					</section>
				) : null}

				{descriptionText ? (
					<Section title="Posting description">
						<p className="whitespace-pre-line text-sm leading-6 text-foreground">
							{descriptionText}
						</p>
					</Section>
				) : null}

				{!hasDescription && !error ? (
					<section className="border-t border-border/70 pt-4">
						<p className="text-sm leading-6 text-muted-foreground">
							This static snapshot has metadata for the posting, but no full
							description text. Use the posting link to inspect the source role.
						</p>
					</section>
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

				{hasStructuredPayloadSection ? (
					<section className="border-t border-border/70 pt-4">
						<JsonBlock label="Additional public fields" value={extraPublicFields} />
						<JsonBlock label="Job description" value={detail?.jobDescription} />
						<JsonBlock label="Compensation" value={detail?.compensation} />
						<JsonBlock label="Job extra payload" value={detail?.jobExtra} />
						<JsonBlock label="Version extra payload" value={detail?.versionExtra} />
					</section>
				) : null}

				<section className="grid gap-3 border-t border-border/70 pt-4 sm:grid-cols-2">
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
				</section>
			</div>
		</article>
	);
}
