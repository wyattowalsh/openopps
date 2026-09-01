import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	EXPECTED_JOB_COLUMNAR_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	JOB_COLUMNAR_KEEP_INDICES,
	SEARCH_VERSION,
	SearchLoadError,
} from "@/components/openopps-search/search-utils";

export type ColumnarJobsChunk = {
	version: number;
	entity: "jobs";
	layout: "columnar";
	columns: string[];
	count: number;
	values: unknown[][];
};

export function validateColumnarJobsChunk(chunk: ColumnarJobsChunk) {
	if (chunk.version === 7) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Columnar jobs snapshot must not use search payload version 7",
		);
	}
	if (chunk.version !== SEARCH_VERSION || chunk.entity !== "jobs" || chunk.layout !== "columnar") {
		throw new SearchLoadError("invalid_chunk", "Unsupported jobs columnar snapshot");
	}
	if (chunk.columns.join("\0") !== EXPECTED_JOB_COLUMNAR_COLUMNS.join("\0")) {
		throw new SearchLoadError("invalid_chunk", "Columnar jobs columns do not match list+filter projection");
	}
	if (!Array.isArray(chunk.values) || chunk.values.length !== chunk.columns.length) {
		throw new SearchLoadError("invalid_chunk", "Columnar jobs values do not match columns");
	}
	for (const column of chunk.values) {
		if (!Array.isArray(column) || column.length !== chunk.count) {
			throw new SearchLoadError("invalid_chunk", "Columnar jobs value length does not match count");
		}
	}
}

export function searchRowsFromColumnarChunk(chunk: ColumnarJobsChunk): SearchRow[] {
	validateColumnarJobsChunk(chunk);
	const width = EXPECTED_JOB_COLUMNS.length;
	const rows: SearchRow[] = Array.from({ length: chunk.count }, () =>
		new Array<SearchRow[number]>(width).fill(null),
	);
	for (let columnIndex = 0; columnIndex < JOB_COLUMNAR_KEEP_INDICES.length; columnIndex += 1) {
		const destination = JOB_COLUMNAR_KEEP_INDICES[columnIndex];
		const values = chunk.values[columnIndex];
		for (let rowIndex = 0; rowIndex < chunk.count; rowIndex += 1) {
			const cell = values[rowIndex];
			rows[rowIndex][destination] =
				cell === undefined || cell === null ? null : (cell as SearchRow[number]);
		}
	}
	return rows;
}

export function columnarChunkFromRows(rows: SearchRow[]): ColumnarJobsChunk {
	return {
		version: SEARCH_VERSION,
		entity: "jobs",
		layout: "columnar",
		columns: [...EXPECTED_JOB_COLUMNAR_COLUMNS],
		count: rows.length,
		values: JOB_COLUMNAR_KEEP_INDICES.map((index) => rows.map((row) => row[index] ?? null)),
	};
}
