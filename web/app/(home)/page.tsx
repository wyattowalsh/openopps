import dynamic from "next/dynamic";
import Link from "next/link";

import { homeJsonLd, homePageMetadata, jsonLdScriptProps } from "@/lib/site-metadata";

/** 50 rows × 68px list-item height. Keep in sync with JOBS_BOARD_PAGE_SIZE * JOB_ROW_HEIGHT. */
const JOBS_BOARD_FIRST_PAINT_LIST_MIN_HEIGHT_PX = 3400;

const FIRST_PAINT_METRICS = [
	{ label: "open jobs", value: "0" },
	{ label: "indexed jobs", value: "0" },
	{ label: "boards", value: "0" },
	{ label: "routes", value: "0" },
] as const;

function JobsBoardFirstPaint() {
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
					<div className="flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-start lg:justify-between">
						<div className="min-w-0">
							<p className="opps-kicker">OpenOpps jobs board</p>
							<h1 className="mt-2 font-heading text-2xl font-semibold leading-tight md:text-3xl">
								Open public opportunities
							</h1>
							<p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
								Static snapshot from{" "}
								<code>kaggle/openoppsdb.sqlite</code>
								. Open roles only — use the{" "}
								<Link
									href="/explorer"
									className="text-primary underline-offset-2 hover:underline"
								>
									dataset explorer
								</Link>{" "}
								for closed postings and provider routes.
							</p>
							<div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
								<span className="openopps-status-chip" data-tone="success">
									open only
								</span>
								<a
									href="https://www.kaggle.com/datasets/wyattowalsh/openoppsdb"
									target="_blank"
									rel="noopener noreferrer"
									className="inline-flex items-center gap-1 text-primary hover:underline"
								>
									Kaggle dataset
								</a>
							</div>
						</div>
						<div className="grid grid-cols-2 gap-2 sm:min-w-[30rem] sm:grid-cols-4">
							{FIRST_PAINT_METRICS.map((metric) => (
								<div key={metric.label} className="opps-metric">
									<div className="font-heading text-xl font-semibold text-primary">
										{metric.value}
									</div>
									<div className="mt-1 truncate font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
										{metric.label}
									</div>
								</div>
							))}
						</div>
					</div>
				</div>

				<div className="opps-toolbar mt-4 space-y-3">
					<div className="grid gap-3 lg:grid-cols-[minmax(16rem,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_auto]">
						<div className="h-[3.25rem] rounded-md border border-border/60 bg-background/40" />
						<div className="h-[3.25rem] rounded-md border border-border/60 bg-background/40" />
						<div className="h-[3.25rem] rounded-md border border-border/60 bg-background/40" />
						<div className="h-8 self-end rounded-md border border-border/60 bg-background/40" />
					</div>
					<div className="h-9 rounded-[var(--opps-radius-md)] border border-border/70 bg-background/55" />
				</div>

				<p className="mt-3 min-h-4 shrink-0 text-xs text-muted-foreground">
					Loading open jobs...
				</p>

				<div
					className="mt-4 rounded-[var(--opps-radius-xl)] border border-dashed border-border/80 bg-background/60"
					data-jobs-board-list-reserve=""
					style={{ minHeight: JOBS_BOARD_FIRST_PAINT_LIST_MIN_HEIGHT_PX }}
				/>
			</div>
		</section>
	);
}

const JobsBoard = dynamic(
	() =>
		import("@/components/jobs-board/jobs-board").then((module) => ({
			default: module.JobsBoard,
		})),
	{
		loading: JobsBoardFirstPaint,
	},
);

export const metadata = homePageMetadata();

export default function HomePage() {
	return (
		<>
			<script {...jsonLdScriptProps(homeJsonLd())} />
			<JobsBoard />
		</>
	);
}
