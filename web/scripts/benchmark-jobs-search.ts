import { gzipSync } from "node:zlib";
import { performance } from "node:perf_hooks";

import { filterAndSortJobs } from "../components/jobs-board/jobs-board-filter-engine";
import {
	createFrozenJobsSearchCorpus,
	frozenJobsSearchCases,
	JobsSearchEngine,
} from "../lib/jobs-search-engine-core";
import type { SearchManifest } from "../components/openopps-search/search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	J,
	SEARCH_VERSION,
	text,
} from "../components/openopps-search/search-utils";

const RUNS = 25;
const WARMUPS = 5;

async function main() {
	const rows = createFrozenJobsSearchCorpus();
	const manifest = frozenManifest(rows.length);
	const buildStarted = performance.now();
	const engine = new JobsSearchEngine({ manifest, rows });
	const buildMs = performance.now() - buildStarted;
	const cases = frozenJobsSearchCases();

	const parity = cases.every((scenario) => {
		const expected = filterAndSortJobs(rows, scenario.filters, scenario.sortKey).slice(
			(scenario.page - 1) * scenario.pageSize,
			scenario.page * scenario.pageSize,
		);
		const actual = engine.search(scenario).rows;
		return JSON.stringify(actual) === JSON.stringify(expected);
	});

	const oracle = measure(() => {
		for (const scenario of cases) {
			filterAndSortJobs(rows, scenario.filters, scenario.sortKey);
		}
	});
	const bitsetCold = measure(() => {
		engine.clearResultCacheForTests();
		for (const scenario of cases) {
			engine.search(scenario);
		}
	});
	const bitsetWarm = measure(() => {
		for (const scenario of cases) {
			engine.search(scenario);
		}
	});
	const json = JSON.stringify(rows);
	const stats = engine.stats();
	const pagefindBuild = await benchmarkPagefind(rows);

	const report = {
		schemaVersion: 1,
		corpus: {
			rows: rows.length,
			cases: cases.length,
			seed: "deterministic-modulo-v1",
		},
		pagefind: {
			version: "1.5.2",
			semanticParity: false,
			build: pagefindBuild,
			blockingSemantics: [
				"fuzzy/subsequence facet values",
				"salary interval overlap",
				"posted-date range intersection",
				"wide versus narrow field selection",
				"OpenOpps weighted relevance and first-seen saved counts",
			],
			note: "Official APIs accept text plus categorical string filters and flat string sorts; the frozen contract cannot be represented without a second full semantic pass.",
		},
		columnarBitsetWorker: {
			semanticParity: parity,
			buildMs: round(buildMs),
			coldMedianMs: bitsetCold.median,
			coldP95Ms: bitsetCold.p95,
			warmMedianMs: bitsetWarm.median,
			warmP95Ms: bitsetWarm.p95,
			indexBytes: stats.indexBytes,
			dictionaryValues: stats.dictionaryValues,
		},
		oracleFullScan: {
			medianMs: oracle.median,
			p95Ms: oracle.p95,
		},
		transferEstimate: {
			rowJsonBytes: Buffer.byteLength(json),
			rowJsonGzipBytes: gzipSync(json, { level: 9 }).byteLength,
			indexBytes: stats.indexBytes,
		},
		heapEstimate: {
			rowPayloadBytesLowerBound: Buffer.byteLength(json),
			typedIndexBytes: stats.indexBytes,
		},
		decision: parity ? "dependency-free-columnar-bitset-worker" : "fail-closed",
	};

	process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
	if (!parity) {
		process.exitCode = 1;
	}
}

void main();

async function benchmarkPagefind(rows: ReturnType<typeof createFrozenJobsSearchCorpus>) {
	const modulePath = process.env.OPENOPPS_PAGEFIND_MODULE?.trim();
	if (!modulePath) {
		return {
			status: "skipped",
			reason: "Set OPENOPPS_PAGEFIND_MODULE to pagefind 1.5.2 lib/index.js.",
		};
	}
	type PagefindIndex = {
		addCustomRecord(record: {
			url: string;
			content: string;
			language: string;
			meta: Record<string, string>;
			filters: Record<string, string[]>;
			sort: Record<string, string>;
		}): Promise<{ errors?: string[] }>;
		getFiles(): Promise<{
			errors?: string[];
			files: Array<{ path: string; content: Uint8Array }>;
		}>;
		deleteIndex(): Promise<void>;
	};
	type PagefindModule = {
		createIndex(): Promise<{ index: PagefindIndex }>;
		close(): Promise<void>;
	};
	const pagefind = (await import(modulePath)) as PagefindModule;
	const started = performance.now();
	const { index } = await pagefind.createIndex();
	try {
		for (let start = 0; start < rows.length; start += 250) {
			const batch = rows.slice(start, start + 250);
			const responses = await Promise.all(
				batch.map((row) =>
					index.addCustomRecord({
						url: `/jobs/${encodeURIComponent(text(row[J.id]))}`,
						content: [
							row[J.title],
							row[J.company],
							row[J.descriptionSnippet],
							row[J.department],
							row[J.team],
							row[J.locations],
							row[J.provider],
						]
							.map(text)
							.join(" "),
						language: "en",
						meta: { id: text(row[J.id]) },
						filters: {
							status: [text(row[J.status])],
							source: [text(row[J.source])],
							provider: [text(row[J.provider])],
							department: [text(row[J.department])],
							team: [text(row[J.team])],
						},
						sort: { latestObserved: text(row[J.latestObserved]) },
					}),
				),
			);
			const errors = responses.flatMap((response) => response.errors ?? []);
			if (errors.length > 0) {
				throw new Error(`Pagefind indexing failed: ${errors.slice(0, 3).join("; ")}`);
			}
		}
		const { files, errors } = await index.getFiles();
		if (errors?.length) {
			throw new Error(`Pagefind output failed: ${errors.slice(0, 3).join("; ")}`);
		}
		return {
			status: "measured",
			buildMs: round(performance.now() - started),
			files: files.length,
			bytes: files.reduce((total, file) => total + file.content.byteLength, 0),
		};
	} finally {
		await index.deleteIndex();
		await pagefind.close();
	}
}

function measure(operation: () => void) {
	const times: number[] = [];
	for (let index = 0; index < WARMUPS + RUNS; index += 1) {
		const started = performance.now();
		operation();
		const elapsed = performance.now() - started;
		if (index >= WARMUPS) {
			times.push(elapsed);
		}
	}
	times.sort((left, right) => left - right);
	return {
		median: round(times[Math.floor(times.length / 2)]),
		p95: round(times[Math.min(times.length - 1, Math.ceil(times.length * 0.95) - 1)]),
	};
}

function round(value: number) {
	return Math.round(value * 100) / 100;
}

function frozenManifest(count: number): SearchManifest {
	return {
		version: SEARCH_VERSION,
		snapshotAt: "2026-07-10T00:00:00Z",
		source: { database: "frozen", tables: ["jobs"] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { count, columns: [...EXPECTED_JOB_COLUMNS], path: "/jobs.json" },
			boards: { count: 0, columns: [...EXPECTED_BOARD_COLUMNS], path: "/boards.json" },
			providers: { count: 0, columns: [...EXPECTED_PROVIDER_COLUMNS], path: "/providers.json" },
		},
		facets: {
			sources: [], providerIds: [], jobStatuses: [], supportLevels: [],
			routeStatuses: [], workplaces: [], employmentTypes: [],
		},
	};
}
