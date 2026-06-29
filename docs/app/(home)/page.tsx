import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Database, DoorOpen } from "lucide-react";

import { Button } from "@/components/ui/button";
import { openOppsData, sourceStats } from "@/lib/openopps-data";

const providerRows = openOppsData.jobProviders.map(
	(provider) =>
		[provider.id, provider.supportLevel, provider.description] as const,
);

function OpenDoorVisual() {
	return (
		<div
			aria-hidden="true"
			className="mb-5 flex min-h-56 items-center gap-5 rounded-[var(--opps-radius-xl)] border bg-background/80 p-5"
		>
			<Image
				src="/brand/openopps-logo.png"
				alt=""
				width={180}
				height={180}
				className="size-32 shrink-0 sm:size-40"
				priority
			/>
			<div className="min-w-0 space-y-3">
				<p className="opps-kicker">Open door</p>
				<p className="text-3xl font-bold leading-none tracking-[-0.04em] text-foreground">
					Public opportunities, ready for the CLI.
				</p>
				<p className="text-sm leading-6 text-muted-foreground">
					Find hiring boards, check provider support, and export jobs from a
					local command line workflow.
				</p>
			</div>
		</div>
	);
}

export default function HomePage() {
	return (
		<div className="relative isolate overflow-hidden px-5 py-10 sm:px-8 lg:px-10">
			<div className="mx-auto grid min-h-[78vh] w-full max-w-7xl items-center gap-8 py-10 lg:grid-cols-[1.05fr_0.95fr] lg:py-20">
				<section className="space-y-8">
					<div className="inline-flex items-center gap-2 rounded-full border bg-card/75 px-3 py-1.5 text-xs font-semibold text-muted-foreground shadow-sm backdrop-blur">
						<Image
							src="/brand/openopps-logo.png"
							alt=""
							width={20}
							height={20}
							className="size-5 rounded-md"
							priority
						/>
						<span>open door to public opportunities</span>
					</div>

					<div className="space-y-5">
						<p className="opps-kicker">OpenOpps developer docs</p>
						<h1 className="max-w-5xl text-balance text-5xl font-bold leading-[0.9] tracking-[-0.075em] sm:text-6xl lg:text-7xl">
							Open the door to public opportunities.
						</h1>
						<p className="max-w-2xl text-pretty text-base leading-7 text-muted-foreground sm:text-lg">
							OpenOpps finds public hiring boards, checks provider support,
							syncs normalized postings, and exports jobs to local files.
						</p>
					</div>

					<div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
						<Button asChild size="lg">
							<Link href="/docs">
								Read the docs
								<ArrowRight className="ml-2 size-4" />
							</Link>
						</Button>
						<Button asChild variant="outline" size="lg">
							<Link href="/jobs">Browse open jobs</Link>
						</Button>
						<Button asChild variant="outline" size="lg">
							<Link href="/docs/cli-reference">CLI reference</Link>
						</Button>
					</div>

					<div className="grid max-w-2xl gap-3 sm:grid-cols-3">
						{sourceStats.map(([label, value, detail]) => (
							<div key={label} className="opps-stat-card">
								<div className="text-3xl font-bold tracking-[-0.08em] text-primary">
									{value}
								</div>
								<div className="mt-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
									{label}
								</div>
								<div className="mt-2 text-xs text-muted-foreground">
									{detail}
								</div>
							</div>
						))}
					</div>
				</section>

				<section className="opps-panel opps-scanline relative overflow-hidden p-4 sm:p-6">
					<div className="absolute right-4 top-4 flex gap-1.5">
						<span className="size-2.5 rounded-full bg-destructive" />
						<span className="size-2.5 rounded-full bg-accent" />
						<span className="size-2.5 rounded-full bg-primary" />
					</div>

					<div className="mb-6 flex items-center gap-3 border-b pb-4">
						<div className="flex size-10 items-center justify-center rounded-xl border bg-background/75">
							<Database className="size-4 text-primary" />
						</div>
						<div>
							<p className="text-sm font-semibold">openopps status</p>
							<p className="text-xs text-muted-foreground">
								uv run openopps status --json
							</p>
						</div>
					</div>

					<OpenDoorVisual />

					<div className="space-y-3 font-mono text-sm">
						<div className="openopps-data-table-wrap p-4 shadow-inner">
							<p className="mb-3 opps-kicker">ready checks</p>
							<div className="space-y-2">
								{providerRows.map(([provider, status, note]) => (
									<div key={provider} className="opps-provider-row">
										<span>{provider}</span>
										<span
											className="openopps-status-chip"
											data-tone={
												status === "jobs" || status === "yes"
													? "jobs"
													: status === "detect" || status === "dry-run"
														? "detect"
														: "unsupported"
											}
										>
											{status}
										</span>
										<span className="col-span-2 text-xs text-muted-foreground">
											{note}
										</span>
									</div>
								))}
							</div>
						</div>

						<div className="grid gap-3 sm:grid-cols-2">
							<div className="rounded-2xl border bg-primary p-4 text-primary-foreground">
								<DoorOpen className="mb-4 size-4" />
								<p className="flex flex-col text-lg font-bold leading-tight tracking-[-0.03em]">
									<span>Clean local</span>
									<span>exports</span>
								</p>
								<p className="mt-1 text-xs opacity-75">
									jsonl, csv, and parquet without a hosted service
								</p>
							</div>
							<div className="rounded-2xl border bg-accent p-4 text-accent-foreground">
								<p className="mb-4 text-xs uppercase tracking-[0.24em] opacity-75">
									export modes
								</p>
								<p className="text-2xl font-bold tracking-[-0.06em]">
									jsonl csv parquet
								</p>
								<p className="mt-1 text-xs opacity-75">
									analysis-ready, no warehouse required
								</p>
							</div>
						</div>
					</div>
				</section>
			</div>
		</div>
	);
}
