import type { LineageAggregate, LineageEdge } from "./search-types";

export type LineageStage = {
	key: "sources" | "providers" | "boards" | "jobs";
	label: string;
	value: number;
	secondaryLabel: string;
	secondaryValue: number;
	edgeLabel?: string;
	edgeCount?: number;
};

export type LineagePathRow = {
	key: string;
	sourceKey: string;
	providerId: string;
	boardKey: string;
	routes: number;
	jobs: number;
	openJobs: number;
	openShare: number;
};

export type LineagePairRow = {
	key: string;
	from: string;
	to: string;
	routes?: number;
	boards?: number;
	jobs: number;
	openJobs: number;
	openShare: number;
};

export type LineageNetworkModel = {
	stages: LineageStage[];
	pathRows: LineagePathRow[];
	sourceProviderRows: LineagePairRow[];
	sourceBoardRows: LineagePairRow[];
	maxPathJobs: number;
	maxSourceProviderJobs: number;
	maxSourceBoardJobs: number;
};

export function buildLineageNetworkModel(
	lineage: LineageAggregate,
	limit = 8,
): LineageNetworkModel {
	const pathRows = rankedEdges(lineage.edges.providerBoards, limit).map((edge) => {
		const boardKey = edge.boardKey ?? "board";
		const sourceKey = edge.sourceKey ?? sourceKeyFromBoard(boardKey) ?? "source";
		const providerId = edge.providerId ?? "provider";
		return {
			key: `${sourceKey}:${providerId}:${boardKey}`,
			sourceKey,
			providerId,
			boardKey,
			routes: edge.routes ?? 0,
			jobs: edge.jobs,
			openJobs: edge.openJobs,
			openShare: lineageOpenJobShare(edge.openJobs, edge.jobs),
		};
	});
	const sourceProviderRows = rankedEdges(lineage.edges.sourceProviders, limit).map(
		(edge) => ({
			key: `${edge.sourceKey ?? "source"}:${edge.providerId ?? "provider"}`,
			from: edge.sourceKey ?? "source",
			to: edge.providerId ?? "provider",
			routes: edge.routes,
			jobs: edge.jobs,
			openJobs: edge.openJobs,
			openShare: lineageOpenJobShare(edge.openJobs, edge.jobs),
		}),
	);
	const sourceBoardRows = rankedEdges(lineage.edges.sourceBoards, limit).map((edge) => ({
		key: `${edge.sourceKey ?? "source"}:${edge.boardKey ?? "board"}`,
		from: edge.sourceKey ?? "source",
		to: edge.boardKey ?? "board",
		boards: edge.boards,
		jobs: edge.jobs,
		openJobs: edge.openJobs,
		openShare: lineageOpenJobShare(edge.openJobs, edge.jobs),
	}));

	return {
		stages: [
			{
				key: "sources",
				label: "Source rows",
				value: lineage.counts.sourceRows,
				secondaryLabel: "source keys",
				secondaryValue: lineage.counts.sources,
				edgeLabel: "source/provider edges",
				edgeCount: lineage.edges.sourceProviders.length,
			},
			{
				key: "providers",
				label: "Provider routes",
				value: lineage.counts.providerRoutes,
				secondaryLabel: "provider ids",
				secondaryValue: lineage.counts.providers,
				edgeLabel: "provider/board flows",
				edgeCount: lineage.edges.providerBoards.length,
			},
			{
				key: "boards",
				label: "Boards",
				value: lineage.counts.boards,
				secondaryLabel: "source/board edges",
				secondaryValue: lineage.edges.sourceBoards.length,
			},
			{
				key: "jobs",
				label: "Jobs",
				value: lineage.counts.jobs,
				secondaryLabel: "open jobs",
				secondaryValue: lineage.counts.openJobs,
			},
		],
		pathRows,
		sourceProviderRows,
		sourceBoardRows,
		maxPathJobs: maxJobs(pathRows),
		maxSourceProviderJobs: maxJobs(sourceProviderRows),
		maxSourceBoardJobs: maxJobs(sourceBoardRows),
	};
}

export function lineageOpenJobShare(openJobs: number, jobs: number) {
	return jobs > 0 ? Math.round((openJobs / jobs) * 100) : 0;
}

function rankedEdges(edges: LineageEdge[], limit: number) {
	return [...edges]
		.filter((edge) => edge.jobs > 0)
		.sort((left, right) => {
			const jobs = right.jobs - left.jobs;
			if (jobs !== 0) {
				return jobs;
			}
			const openJobs = right.openJobs - left.openJobs;
			if (openJobs !== 0) {
				return openJobs;
			}
			return edgeKey(left).localeCompare(edgeKey(right));
		})
		.slice(0, limit);
}

function sourceKeyFromBoard(boardKey: string) {
	const separator = boardKey.indexOf(":");
	return separator > 0 ? boardKey.slice(0, separator) : undefined;
}

function maxJobs(rows: Array<{ jobs: number }>) {
	return Math.max(1, ...rows.map((row) => row.jobs));
}

function edgeKey(edge: LineageEdge) {
	return `${edge.sourceKey ?? ""}:${edge.providerId ?? ""}:${edge.boardKey ?? ""}`;
}
