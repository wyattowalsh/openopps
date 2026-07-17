import { PAGE_SIZE } from "@/components/openopps-search/explorer-filter-engine";
import { formatCount } from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";

type ExplorerPaginationProps = {
	visibleLimit: number;
	total: number;
	canLoadFullJobs?: boolean;
	onMore: () => void;
	onLoadFullJobs?: () => void;
};

export function ExplorerPagination({
	visibleLimit,
	total,
	canLoadFullJobs,
	onMore,
	onLoadFullJobs,
}: ExplorerPaginationProps) {
	if (visibleLimit < total) {
		return (
			<div className="flex justify-center pt-2">
				<Button type="button" variant="outline" onClick={onMore}>
					Show {formatCount(Math.min(PAGE_SIZE, total - visibleLimit))} more
				</Button>
			</div>
		);
	}

	if (canLoadFullJobs && onLoadFullJobs) {
		return (
			<div className="flex justify-center pt-2">
				<Button type="button" variant="outline" onClick={onLoadFullJobs}>
					Load full jobs index
				</Button>
			</div>
		);
	}

	return null;
}
