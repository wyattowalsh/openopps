import { Loader2 } from "lucide-react";

export default function JobsLoading() {
	return (
		<section className="not-prose mx-auto w-full max-w-[72rem] px-3 py-6 sm:px-5 lg:px-6">
			<div className="opps-loading min-h-[24rem]">
				<Loader2 className="size-4 animate-spin" />
				Loading job detail...
			</div>
		</section>
	);
}
