import type { ComponentType, ReactNode, SVGProps } from "react";
import Link from "next/link";

import type { Entity, SearchTopValue } from "@/components/openopps-search/search-types";
import { formatCount } from "@/components/openopps-search/search-utils";
import { cn } from "@/lib/utils";

export type CoverageTone = "primary" | "info" | "warning";

export type RankedLedgerItem = {
	key: string;
	label: string;
	count: number;
	barPercent: number;
	snapshotPercent?: number;
	countLabel?: string;
	tone?: CoverageTone;
	badge?: string;
	innerPercent?: number;
	href?: string;
	onActivate?: () => void;
	activateLabel?: string;
};

export function clampCoveragePercent(value: number | undefined) {
	if (!Number.isFinite(value)) {
		return 0;
	}
	return Math.max(0, Math.min(100, Math.round(Number(value))));
}

export function coverageShare(part: number | undefined, total: number | undefined) {
	if (!Number.isFinite(part) || !Number.isFinite(total) || !total || total <= 0) {
		return 0;
	}
	return clampCoveragePercent((Number(part) / Number(total)) * 100);
}

export function formatLedgerRank(index: number) {
	return String(index + 1).padStart(2, "0");
}

export function jobsBoardSearchHref(params: Record<string, string | undefined>) {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		const trimmed = value?.trim();
		if (trimmed) {
			search.set(key, trimmed);
		}
	}
	const query = search.toString();
	return query ? `/?${query}` : "/";
}

export function routeHealthTone(value: string): "success" | "warning" | "error" | "info" {
	const normalized = value.trim().toLowerCase();
	if (
		normalized === "full" ||
		normalized === "ok" ||
		normalized === "success" ||
		normalized === "yes" ||
		normalized === "healthy" ||
		normalized === "supported"
	) {
		return "success";
	}
	if (
		normalized === "detect" ||
		normalized === "dry-run" ||
		normalized === "warning" ||
		normalized === "partial" ||
		normalized === "limited"
	) {
		return "warning";
	}
	if (
		normalized === "unsupported" ||
		normalized === "no" ||
		normalized === "error" ||
		normalized === "failed" ||
		normalized === "fail" ||
		normalized === "broken"
	) {
		return "error";
	}
	return "info";
}

export function rankedTopValueItems(
	values: SearchTopValue[] | undefined,
	options: {
		labels?: Map<string, string>;
		limit?: number;
		snapshotTotal?: number;
		tone?: CoverageTone;
		hrefFor?: (value: string) => string | undefined;
		onSelect?: (value: string) => void;
		inspectNoun?: string;
	} = {},
): RankedLedgerItem[] {
	const limit = options.limit ?? 8;
	const rows = (values ?? []).filter((item) => item.value).slice(0, limit);
	const maxCount = Math.max(1, ...rows.map((item) => item.count));
	return rows.map((item) => {
		const label = options.labels?.get(item.value) ?? item.value;
		const href = options.hrefFor?.(item.value);
		return {
			key: item.value,
			label,
			count: item.count,
			barPercent: coverageShare(item.count, maxCount),
			snapshotPercent:
				options.snapshotTotal != null
					? coverageShare(item.count, options.snapshotTotal)
					: undefined,
			tone: options.tone,
			href,
			onActivate:
				!href && options.onSelect ? () => options.onSelect?.(item.value) : undefined,
			activateLabel: href
				? `Open ${label} on jobs board`
				: options.onSelect
					? `Inspect ${options.inspectNoun ?? "rows"} for ${label}`
					: undefined,
		};
	});
}

export function CoverageMeter({
	percent,
	tone = "primary",
	label,
}: {
	percent: number;
	tone?: CoverageTone;
	label?: string;
}) {
	const width = clampCoveragePercent(percent);
	return (
		<div className="mt-2 flex min-w-0 items-center gap-2">
			<div
				className="h-2 min-w-0 flex-1 overflow-hidden rounded-[var(--opps-radius-sm)] bg-muted"
				role="meter"
				aria-valuemin={0}
				aria-valuemax={100}
				aria-valuenow={width}
				aria-label={label ?? "Coverage"}
			>
				<div
					className={cn("h-full", coverageFillClass(tone))}
					style={{ width: `${width}%` }}
					aria-hidden="true"
				/>
			</div>
			{label ? (
				<span className="shrink-0 font-mono text-[0.68rem] tabular-nums tracking-normal text-muted-foreground">
					{label}
				</span>
			) : null}
		</div>
	);
}

export function RankedLedgerList({
	items,
	emptyLabel,
}: {
	items: RankedLedgerItem[];
	emptyLabel: string;
}) {
	if (items.length === 0) {
		return (
			<p className="rounded-[var(--opps-radius-md)] border border-dashed border-border/80 px-3 py-3 text-sm text-muted-foreground">
				{emptyLabel}
			</p>
		);
	}
	return (
		<ul className="min-w-0 space-y-2">
			{items.map((item, index) => (
				<li key={item.key} className="min-w-0">
					<RankedLedgerRow item={item} rank={index} />
				</li>
			))}
		</ul>
	);
}

export function RankedLedgerRow({
	item,
	rank,
}: {
	item: RankedLedgerItem;
	rank: number;
}) {
	const interactive = Boolean(item.href || item.onActivate);
	const className = cn(
		"opps-provider-row min-w-0 w-full",
		interactive &&
			"hover:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
	);
	const body = <RankedLedgerRowBody item={item} rank={rank} />;
	if (item.href) {
		return (
			<Link href={item.href} className={className} aria-label={item.activateLabel}>
				{body}
			</Link>
		);
	}
	if (item.onActivate) {
		return (
			<button
				type="button"
				onClick={item.onActivate}
				className={cn(className, "text-left")}
				aria-label={item.activateLabel}
			>
				{body}
			</button>
		);
	}
	return <div className={className}>{body}</div>;
}

function RankedLedgerRowBody({
	item,
	rank,
}: {
	item: RankedLedgerItem;
	rank: number;
}) {
	const tone = item.tone ?? "primary";
	const barPercent = clampCoveragePercent(item.barPercent);
	const innerPercent =
		item.innerPercent == null ? null : clampCoveragePercent(item.innerPercent);
	const badgeTone = item.badge ? routeHealthTone(item.badge) : null;
	return (
		<>
			<div className="min-w-0">
				<div className="flex min-w-0 items-center gap-2 text-xs">
					<span className="shrink-0 font-mono tabular-nums tracking-normal text-muted-foreground">
						{formatLedgerRank(rank)}
					</span>
					<span className="min-w-0 truncate font-semibold">{item.label}</span>
					{item.badge && badgeTone ? (
						<span className="openopps-status-chip shrink-0" data-tone={badgeTone}>
							{item.badge}
						</span>
					) : null}
				</div>
				<div className="mt-1 flex min-w-0 items-center gap-2">
					<div className="h-2 min-w-0 flex-1 overflow-hidden rounded-[var(--opps-radius-sm)] bg-muted">
						{innerPercent == null ? (
							<div
								className={cn("h-full", coverageFillClass(tone))}
								style={{ width: `${barPercent}%` }}
								aria-hidden="true"
							/>
						) : (
							<div
								className="h-full bg-border"
								style={{ width: `${barPercent}%` }}
								aria-hidden="true"
							>
								<div
									className="h-full bg-primary"
									style={{ width: `${innerPercent}%` }}
									aria-hidden="true"
								/>
							</div>
						)}
					</div>
				</div>
			</div>
			<div className="shrink-0 text-right font-mono text-xs tabular-nums tracking-normal">
				<div>{item.countLabel ?? formatCount(item.count)}</div>
				{item.snapshotPercent != null ? (
					<div className="text-[0.68rem] text-muted-foreground">
						{item.snapshotPercent}%
					</div>
				) : null}
			</div>
		</>
	);
}

export function ExplorerEmptyPanel({
	heading,
	children,
	action,
	className,
}: {
	heading?: string;
	children: ReactNode;
	action?: ReactNode;
	className?: string;
}) {
	return (
		<div className={cn("opps-empty min-w-0", className)}>
			{heading ? (
				<h2 className="font-heading text-base font-semibold tracking-normal">
					{heading}
				</h2>
			) : null}
			<div className="mt-2 max-w-xl text-sm leading-6">{children}</div>
			{action ? <div className="mt-4">{action}</div> : null}
		</div>
	);
}

export function ExplorerMetric({
	label,
	value,
	sharePercent,
	shareLabel,
	tone = "primary",
	onActivate,
	href,
	className,
}: {
	label: string;
	value?: number;
	sharePercent?: number;
	shareLabel?: string;
	tone?: CoverageTone;
	onActivate?: () => void;
	href?: string;
	className?: string;
}) {
	const interactive = Boolean(onActivate || href);
	const body = (
		<>
			<div className="font-heading text-xl font-semibold text-primary">
				{formatCount(value)}
			</div>
			<div className="mt-1 truncate font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
				{label}
			</div>
			{sharePercent != null ? (
				<CoverageMeter
					percent={sharePercent}
					tone={tone}
					label={shareLabel}
				/>
			) : null}
		</>
	);
	const metricClassName = cn(
		"opps-metric min-w-0",
		interactive && "hover:border-primary/45",
		className,
	);
	if (href) {
		return (
			<Link href={href} className={cn(metricClassName, "block")} aria-label={label}>
				{body}
			</Link>
		);
	}
	if (onActivate) {
		return (
			<button
				type="button"
				onClick={onActivate}
				className={cn(metricClassName, "w-full text-left")}
				aria-label={`Inspect ${label}`}
			>
				{body}
			</button>
		);
	}
	return <div className={metricClassName}>{body}</div>;
}

export function ExplorerFilterSelect({
	label,
	value,
	onChange,
	options,
	icon: Icon,
	className,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	options: Array<{ value: string; label: string }>;
	icon?: ComponentType<SVGProps<SVGSVGElement>>;
	className?: string;
}) {
	return (
		<label className={cn("grid min-w-0 max-w-full gap-1.5 text-sm font-semibold", className)}>
			<span className="flex min-w-0 items-center gap-2">
				{Icon ? <Icon className="size-4 shrink-0" /> : null}
				{label}
			</span>
			<select
				value={value}
				onChange={(event) => onChange(event.target.value)}
				className="opps-select w-full min-w-0 max-w-full overflow-hidden text-ellipsis"
				aria-label={label}
			>
				{options.map((option) => (
					<option key={`${label}-${option.value}`} value={option.value}>
						{option.label}
					</option>
				))}
			</select>
		</label>
	);
}

export function explorerFacetOptions(values: string[] | undefined) {
	return [
		{ value: "", label: "Any" },
		...(values ?? []).map((value) => ({ value, label: value })),
	];
}

export function explorerEntityLabel(entity: Entity) {
	if (entity === "providers") {
		return "board providers";
	}
	return entity;
}

export function formatExplorerNullableNumber(value: unknown) {
	if (value === null || value === undefined || value === "") {
		return "";
	}
	const numeric = Number(value);
	if (!Number.isFinite(numeric)) {
		return "";
	}
	return formatCount(numeric);
}

function coverageFillClass(tone: CoverageTone) {
	if (tone === "warning") {
		return "bg-warning";
	}
	if (tone === "info") {
		return "bg-info";
	}
	return "bg-primary";
}
