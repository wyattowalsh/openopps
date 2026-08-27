import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	canonicalJobUrl,
	cleanText,
	formatJobDetailTitle,
	isIndexableJobDetail,
	jobBoardDeepLink,
	jobDescriptionText,
	jobPostingJsonLd,
	serializeJsonLdScript,
	safeJobExternalUrl,
} from "@/lib/job-detail-utils";
import { getPublicJobDetail } from "@/lib/jobs-public-data";
import { appName, socialImages } from "@/lib/shared";
import { jobBreadcrumbJsonLd, jsonLdScriptProps } from "@/lib/site-metadata";

type JobDeepLinkPageProps = {
	params: Promise<{ id: string }>;
};

export const dynamicParams = true;

export async function generateMetadata({
	params,
}: JobDeepLinkPageProps): Promise<Metadata> {
	const { id } = await params;
	const detail = await getPublicJobDetail(id);
	if (!detail) {
		return {
			title: "Job not found",
			robots: { index: false, follow: false },
		};
	}
	const title = formatJobDetailTitle(detail);
	const description = jobDescriptionText(detail);
	const url = canonicalJobUrl(detail.id);
	const indexable = isIndexableJobDetail(detail);
	return {
		title,
		description,
		robots: indexable ? undefined : { index: false, follow: false },
		alternates: indexable
			? {
					canonical: url,
				}
			: undefined,
		openGraph: {
			title: `${title} | ${appName}`,
			description,
			url,
			type: "article",
			images: [
				{
					url: socialImages.database,
					width: 1200,
					height: 630,
					alt: `${appName} jobs snapshot`,
				},
			],
		},
		twitter: {
			card: "summary_large_image",
			title: `${title} | ${appName}`,
			description,
			images: [socialImages.database],
		},
	};
}

export default async function JobDeepLinkPage({ params }: JobDeepLinkPageProps) {
	const { id } = await params;
	const detail = await getPublicJobDetail(id);
	if (!detail) {
		notFound();
	}
	const title = formatJobDetailTitle(detail);
	const description = jobDescriptionText(detail, 4_000);
	const postingUrl = safeJobExternalUrl(detail.postingUrl);
	const applyUrl = safeJobExternalUrl(detail.applyUrl);
	const jsonLd = jobPostingJsonLd(detail);
	const indexable = isIndexableJobDetail(detail);

	return (
		<section className="not-prose mx-auto w-full max-w-[72rem] px-3 py-6 sm:px-5 lg:px-6">
			{indexable ? (
				<script {...jsonLdScriptProps(jobBreadcrumbJsonLd({ title, jobId: detail.id }))} />
			) : null}
			{jsonLd ? (
				<script
					type="application/ld+json"
					dangerouslySetInnerHTML={{ __html: serializeJsonLdScript(jsonLd) }}
				/>
			) : null}
				<article className="opps-result-card space-y-5 p-5 sm:p-6">
					<div className="flex flex-wrap items-center gap-2">
						<Badge variant="success">{cleanText(detail.status) || "snapshot"}</Badge>
					{detail.providerId ? <Badge variant="outline">{detail.providerId}</Badge> : null}
					{detail.sourceKey ? <Badge variant="outline">{detail.sourceKey}</Badge> : null}
				</div>

				<div className="space-y-2">
					<h1 className="break-words font-heading text-3xl font-semibold leading-tight">
						{cleanText(detail.title) || "Untitled role"}
					</h1>
					{detail.company ? (
						<p className="text-lg text-muted-foreground">{detail.company}</p>
					) : null}
				</div>

				<div className="grid gap-3 border-y border-border/70 py-4 sm:grid-cols-2 lg:grid-cols-3">
					<Field label="Location" value={(detail.locations ?? []).join(", ")} />
					<Field label="Workplace" value={detail.workplaceType ?? detail.remote} />
					<Field label="Employment" value={detail.employmentType} />
					<Field label="Posted" value={detail.postedAt} />
					<Field label="Last observed" value={detail.lastSeenAt} />
					<Field label="Job id" value={detail.id} />
				</div>

				<div className="flex flex-wrap gap-2">
					<Button asChild size="sm">
						<Link href={jobBoardDeepLink(detail.id)}>Open in jobs board</Link>
					</Button>
					{applyUrl ? (
						<Button asChild variant="outline" size="sm">
							<a href={applyUrl} target="_blank" rel="noopener noreferrer">
								Apply
							</a>
						</Button>
					) : null}
					{postingUrl && postingUrl !== applyUrl ? (
						<Button asChild variant="outline" size="sm">
							<a href={postingUrl} target="_blank" rel="noopener noreferrer">
								Source posting
							</a>
						</Button>
					) : null}
				</div>

				<div className="rounded-[var(--opps-radius-md)] border border-border/70 bg-card/70 p-4 text-sm leading-6 text-muted-foreground">
					{description}
				</div>

				<p className="text-xs leading-5 text-muted-foreground">
					This page is generated from the committed OpenOpps static snapshot. Use
					the source posting or apply link for the employer&apos;s current canonical
					posting state.
				</p>
			</article>
		</section>
	);
}

function Field({
	label,
	value,
}: {
	label: string;
	value: string | null | undefined;
}) {
	const cleanValue = cleanText(value);
	if (!cleanValue) {
		return null;
	}
	return (
		<div className="grid gap-1 text-sm">
			<span className="font-mono text-[0.65rem] font-semibold text-muted-foreground">
				{label}
			</span>
			<span className="min-w-0 break-words">{cleanValue}</span>
		</div>
	);
}
