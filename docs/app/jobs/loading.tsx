import { Loader2 } from "lucide-react";

export default function JobsLoading() {
	return (
		<section className="mx-auto w-full max-w-7xl px-5 py-8 sm:px-8 lg:px-10">
			<div className="rounded-[1.4rem] border border-border/75 bg-card/85 p-6 shadow-[0_24px_80px_color-mix(in_oklab,var(--foreground)_8%,transparent)]">
				<div className="space-y-4">
					<div className="h-4 w-32 animate-pulse rounded bg-muted" />
					<div className="h-8 w-2/3 max-w-lg animate-pulse rounded bg-muted" />
					<div className="h-20 w-full animate-pulse rounded-2xl bg-muted/70" />
					<div className="flex min-h-[24rem] items-center justify-center rounded-2xl border border-border/75 bg-background/55">
						<Loader2 className="size-5 animate-spin text-muted-foreground" />
						<span className="ml-2 text-sm text-muted-foreground">
							Loading jobs board…
						</span>
					</div>
				</div>
			</div>
		</section>
	);
}