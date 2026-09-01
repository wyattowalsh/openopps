export type ChunkFetchPlace = {
	hardwareConcurrency?: number | null;
	saveData?: boolean | null;
	effectiveType?: string | null;
};

const DEFAULT_CORES = 4;
const MIN_POOL = 2;
const MAX_POOL = 8;
const SAVE_DATA_POOL = 1;

export function resolveChunkFetchConcurrency(place: ChunkFetchPlace = {}): number {
	const effectiveType = place.effectiveType?.toLowerCase();
	if (place.saveData || effectiveType === "slow-2g" || effectiveType === "2g") {
		return SAVE_DATA_POOL;
	}
	const cores = Number.isFinite(place.hardwareConcurrency)
		? Math.max(1, Math.floor(Number(place.hardwareConcurrency)))
		: DEFAULT_CORES;
	return Math.min(MAX_POOL, Math.max(MIN_POOL, cores));
}

export function resolveBrowserChunkFetchConcurrency(): number {
	if (typeof navigator === "undefined") {
		return resolveChunkFetchConcurrency();
	}
	const connection = (
		navigator as Navigator & {
			connection?: { saveData?: boolean; effectiveType?: string };
		}
	).connection;
	return resolveChunkFetchConcurrency({
		hardwareConcurrency: navigator.hardwareConcurrency,
		saveData: connection?.saveData,
		effectiveType: connection?.effectiveType,
	});
}
