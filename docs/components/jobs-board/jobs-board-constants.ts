export const JOBS_BOARD_PAGE_SIZE = 50;

export function bucketMatchCount(value: number) {
	if (value === 0) return "0";
	if (value < 10) return "1-9";
	if (value < 100) return "10-99";
	if (value < 1000) return "100-999";
	return "1000+";
}