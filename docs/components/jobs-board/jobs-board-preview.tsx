"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import type { JobDetail, SearchRow } from "@/components/openopps-search/search-types";
import {
	formatDate,
	formatLocations,
	formatSalary,
	J,
	text,
} from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

type JobsBoardPreviewProps = {
	row: SearchRow | null;
	detail: JobDetail | null;
	loading: boolean;
	error: string | null;
	onClose?: () => void;
};

function Field({ label, value }: { label: string; value: string }) {
	if (!value) {
		return null;
	}
	return (
		<div className="grid gap-0.5 text-sm">
			<span className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
				{label}
			</span>
			<span className="text-foreground">{value}</span>
		</div>
	);
}

function useSanitizedHtml(value: string | null | undefined) {
	const source = value ?? "";
	const [sanitized, setSanitized] = useState({ source: "", html: "" });

	useEffect(() => {
		if (!source) {
			return;
		}
		let mounted = true;
		void import("isomorphic-dompurify").then((mod) => {
			if (!mounted) {
				return;
			}
			const html = mod.default.sanitize(source, {
				USE_PROFILES: { html: true },
			});
			setSanitized({ source, html });
		});
		return () => {
			mounted = false;
		};
	}, [source]);

	if (!source) {
		return "";
	}
	return sanitized.source === source ? sanitized.html : "";
}

export function JobsBoardPreview({
	row,
	detail,
	loading,
	error,
	onClose,
}: JobsBoardPreviewProps) {
	const descriptionHtml = useSanitizedHtml(
		detail?.descriptionHtml ?? detail?.description,
	);

	if (!row) {
		return (
			<div className="opps-empty h-full min-h-[24rem] lg:min-h-[32rem] text-sm text-muted-foreground">
				Select a job to preview posting details.
			</div>
		);
	}

	const title = text(row[J.title]) || "Untitled role";
	const company = text(row[J.company]) || text(row[J.board]);
	const applyUrl = text(detail?.applyUrl) || text(row[J.url]);
	const postingUrl = text(detail?.postingUrl) || text(row[J.url]);

	return (
		<article className="opps-result-card flex h-full min-h-[24rem] flex-col overflow-hidden lg:min-h-[32rem]">
			<div className="border-b border-border/70 p-4">
				<div className="flex flex-wrap items-center gap-2">
					<span className="openopps-status-chip" data-tone="jobs">
						open
					</span>
					<span className="font-mono text-xs text-muted-foreground">
						{text(row[J.provider])} / {text(row[J.source])}
					</span>
				</div>
				<h2 className="mt-3 break-words font-heading text-xl font-semibold leading-snug">
					{title}
				</h2>
				<p className="mt-1 text-sm text-muted-foreground">{company}</p>
				<div className="mt-4 flex flex-wrap gap-2">
					{applyUrl ? (
						<Button asChild size="sm">
							<a href={applyUrl} target="_blank" rel="noreferrer">
								Apply
								<ExternalLink className="ml-2 size-3.5" />
							</a>
						</Button>
					) : null}
					{postingUrl ? (
						<Button asChild variant="outline" size="sm">
							<a href={postingUrl} target="_blank" rel="noreferrer">
								Posting
								<ExternalLink className="ml-2 size-3.5" />
							</a>
						</Button>
					) : null}
					{onClose ? (
						<Button type="button" variant="ghost" size="sm" onClick={onClose}>
							Close
						</Button>
					) : null}
				</div>
			</div>

			<div className="flex-1 space-y-4 overflow-y-auto p-4">
				<div className="grid gap-3 sm:grid-cols-2">
					<Field label="Location" value={formatLocations(row[J.locations])} />
					<Field
						label="Workplace"
						value={[text(row[J.workplace]), text(row[J.remote])]
							.filter(Boolean)
							.join(" / ")}
					/>
					<Field label="Employment" value={text(row[J.type])} />
					<Field label="Salary" value={formatSalary(row) || text(detail?.salary)} />
					<Field
						label="Team"
						value={[text(row[J.department]), text(row[J.team])]
							.filter(Boolean)
							.join(" / ")}
					/>
					<Field label="Posted" value={formatDate(text(row[J.posted]))} />
					<Field label="Observed" value={formatDate(text(row[J.latestObserved]))} />
				</div>

				{text(row[J.descriptionSnippet]) ? (
					<div className="rounded-xl border border-border/70 bg-card/70 p-3 text-sm leading-6 text-muted-foreground">
						{text(row[J.descriptionSnippet])}
					</div>
				) : null}

				{loading ? (
					<div className="flex items-center gap-2 text-sm text-muted-foreground">
						<Loader2 className="size-4 animate-spin" />
						Loading full description…
					</div>
				) : null}

				{error ? (
					<p className="text-sm text-destructive">
						{error} Showing index snippet only.
					</p>
				) : null}

				{descriptionHtml ? (
					<div
						className="prose prose-sm max-w-none text-foreground [&_a]:text-primary [&_li]:my-1 [&_p]:my-2 [&_ul]:my-2"
						dangerouslySetInnerHTML={{ __html: descriptionHtml }}
					/>
				) : null}

				{detail?.skills && detail.skills.length > 0 ? (
					<div className="space-y-2">
						<p className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
							Skills
						</p>
						<div className="flex flex-wrap gap-1.5">
							{detail.skills.map((skill, index) => (
								<span
									key={`${skill.name ?? "skill"}-${index}`}
									className="rounded-md border border-border/70 bg-background/80 px-2 py-0.5 font-mono text-xs text-muted-foreground"
								>
									{skill.name ?? "Skill"}
								</span>
							))}
						</div>
					</div>
				) : null}
			</div>
		</article>
	);
}
