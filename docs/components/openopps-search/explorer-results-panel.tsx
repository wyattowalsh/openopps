"use client";

import { ExternalLink } from "lucide-react";
import {
	type KeyboardEvent,
	type ReactNode,
	useCallback,
	useRef,
	useState,
} from "react";

import {
	B,
	J,
	P,
} from "@/components/openopps-search/explorer-filter-engine";
import { resolveExplorerListKeyAction } from "@/components/openopps-search/explorer-list-keydown";
import type { Entity, SearchRow } from "@/components/openopps-search/search-types";
import {
	formatDate,
	formatLocations,
	formatSalary,
	text,
} from "@/components/openopps-search/search-utils";

import { safeJobExternalUrl } from "@/lib/job-url";
import { ExplorerPagination } from "./explorer-pagination";
import { explorerEntityLabel, formatExplorerNullableNumber } from "./explorer-shared";

type ExplorerResultsPanelProps = {
	entity: Entity;
	rows: SearchRow[];
	total: number;
	visibleLimit: number;
	onMore: () => void;
	canLoadFullJobs?: boolean;
	onLoadFullJobs?: () => void;
};

export function ExplorerResultsPanel({
	entity,
	rows,
	total,
	visibleLimit,
	onMore,
	canLoadFullJobs,
	onLoadFullJobs,
}: ExplorerResultsPanelProps) {
	const listRef = useRef<HTMLDivElement>(null);
	const [focusedIndex, setFocusedIndex] = useState(-1);
	const activeFocusedIndex =
		rows.length === 0
			? -1
			: focusedIndex >= rows.length
				? rows.length - 1
				: focusedIndex;

	const focusCard = useCallback((index: number) => {
		const cards = listRef.current?.querySelectorAll<HTMLElement>("[data-explorer-card]");
		const card = cards?.[index];
		if (!card) {
			return;
		}
		card.focus({ preventScroll: true });
		card.scrollIntoView?.({ block: "nearest" });
	}, []);

	const handleListKeyDown = useCallback(
		(event: KeyboardEvent<HTMLDivElement>) => {
			const action = resolveExplorerListKeyAction({
				key: event.key,
				focusedIndex: activeFocusedIndex,
				rowCount: rows.length,
			});
			if (!action) {
				return;
			}
			event.preventDefault();
			setFocusedIndex(action.nextIndex);
			if (action.activateLink) {
				const cards = listRef.current?.querySelectorAll<HTMLElement>(
					"[data-explorer-card]",
				);
				const card = cards?.[action.nextIndex];
				const link = card?.querySelector<HTMLAnchorElement>("a[href]");
				link?.click();
				return;
			}
			focusCard(action.nextIndex);
		},
		[activeFocusedIndex, focusCard, rows.length],
	);

	if (rows.length === 0) {
		return (
			<div className="opps-empty-state mt-4">
				No {explorerEntityLabel(entity)} match the current filters.
			</div>
		);
	}

	return (
		<div className="mt-4 space-y-3">
			<div
				ref={listRef}
				className="space-y-3"
				role="list"
				aria-label={`${explorerEntityLabel(entity)} results`}
				tabIndex={0}
				onKeyDown={handleListKeyDown}
			>
				{rows.map((row, index) => {
					if (entity === "jobs") {
						return (
							<JobResult
								key={text(row[J.id])}
								row={row}
								focused={activeFocusedIndex === index}
							/>
						);
					}
					if (entity === "boards") {
						return (
							<BoardResult
								key={text(row[B.key])}
								row={row}
								focused={activeFocusedIndex === index}
							/>
						);
					}
					return (
						<ProviderResult
							key={text(row[P.id])}
							row={row}
							focused={activeFocusedIndex === index}
						/>
					);
				})}
			</div>
			<ExplorerPagination
				visibleLimit={visibleLimit}
				total={total}
				canLoadFullJobs={canLoadFullJobs}
				onMore={onMore}
				onLoadFullJobs={onLoadFullJobs}
			/>
		</div>
	);
}

function ExplorerResultCard({
	children,
	focused,
}: {
	children: ReactNode;
	focused: boolean;
}) {
	return (
		<article
			className="opps-result-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
			role="listitem"
			data-explorer-card
			data-focused={focused ? "true" : "false"}
			tabIndex={-1}
		>
			{children}
		</article>
	);
}

function JobResult({ row, focused }: { row: SearchRow; focused: boolean }) {
	return (
		<ExplorerResultCard focused={focused}>
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<span
							className="openopps-status-chip"
							data-tone={text(row[J.status]) === "open" ? "jobs" : "unsupported"}
						>
							{text(row[J.status]) || "unknown"}
						</span>
						<span className="font-mono text-xs text-muted-foreground">
							{text(row[J.provider]) || "provider"} /{" "}
							{text(row[J.source]) || "source"}
						</span>
					</div>
					<h3 className="mt-3 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[J.title]) || "Untitled role"}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">
						{text(row[J.company]) || text(row[J.board])}
					</p>
				</div>
				<ResultLink href={text(row[J.url])} label="Posting" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
				<Field label="Location" value={formatLocations(row[J.locations])} />
				<Field
					label="Workplace"
					value={[text(row[J.workplace]), text(row[J.remote])]
						.filter(Boolean)
						.join(" / ")}
				/>
				<Field label="Type" value={text(row[J.type])} />
				<Field label="Observed" value={formatDate(text(row[J.latestObserved]))} />
				<Field
					label="Team"
					value={[text(row[J.department]), text(row[J.team])]
						.filter(Boolean)
						.join(" / ")}
				/>
				<Field label="Salary" value={formatSalary(row)} />
				<Field label="Board" value={text(row[J.board])} />
				<Field label="Posted" value={formatDate(text(row[J.posted]))} />
			</div>
		</ExplorerResultCard>
	);
}

function BoardResult({ row, focused }: { row: SearchRow; focused: boolean }) {
	return (
		<ExplorerResultCard focused={focused}>
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<p className="font-mono text-xs text-muted-foreground">
						{text(row[B.source]) || "source"} / {text(row[B.key])}
					</p>
					<h3 className="mt-2 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[B.name]) || text(row[B.domain]) || text(row[B.key])}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">{text(row[B.domain])}</p>
				</div>
				<ResultLink href={text(row[B.url])} label="Board" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
				<Field label="Staff" value={formatExplorerNullableNumber(row[B.staff])} />
				<Field label="Jobs hint" value={formatExplorerNullableNumber(row[B.hint])} />
				<Field label="Source" value={text(row[B.source])} />
			</div>
		</ExplorerResultCard>
	);
}

function ProviderResult({ row, focused }: { row: SearchRow; focused: boolean }) {
	return (
		<ExplorerResultCard focused={focused}>
			<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<span className="openopps-status-chip" data-tone={text(row[P.support])}>
							{text(row[P.support]) || "unknown"}
						</span>
						{text(row[P.status]) ? (
							<span className="openopps-status-chip" data-tone={text(row[P.status])}>
								{text(row[P.status])}
							</span>
						) : null}
					</div>
					<h3 className="mt-3 break-words font-heading text-lg font-semibold leading-snug">
						{text(row[P.label]) || text(row[P.provider])}
					</h3>
					<p className="mt-1 text-sm text-muted-foreground">
						{text(row[P.provider])} route for {text(row[P.board])}
					</p>
				</div>
				<ResultLink href={text(row[P.url])} label="Route" />
			</div>
			<div className="mt-4 grid gap-2 text-sm sm:grid-cols-4">
				<Field label="Source" value={text(row[P.source])} />
				<Field label="Provider" value={text(row[P.provider])} />
				<Field label="Jobs hint" value={formatExplorerNullableNumber(row[P.count])} />
				<Field label="Route id" value={text(row[P.id])} />
			</div>
		</ExplorerResultCard>
	);
}

function Field({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-xl border border-border/60 bg-card/65 px-3 py-2">
			<div className="font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 min-h-5 truncate text-foreground">{value || "n/a"}</div>
		</div>
	);
}

function ResultLink({ href, label }: { href: string; label: string }) {
	const safeHref = safeJobExternalUrl(href);
	if (!safeHref) {
		return null;
	}
	return (
		<a
			href={safeHref}
			target="_blank"
			rel="noopener noreferrer"
			className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-[var(--opps-radius-md)] border border-border bg-card px-3 text-sm font-semibold text-foreground transition hover:border-primary/50 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
			aria-label={`Open ${label} in new tab`}
		>
			{label}
			<ExternalLink className="size-3.5" />
		</a>
	);
}
