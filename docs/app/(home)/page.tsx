import type { Metadata } from "next";
import { Suspense } from "react";

import { JobsBoard } from "@/components/jobs-board/jobs-board";
import { appName } from "@/lib/shared";

export const metadata: Metadata = {
	title: "Jobs board",
	description:
		"Search open public hiring opportunities from the OpenOpps static search index.",
	openGraph: {
		title: `Jobs board | ${appName}`,
		description:
			"Filter and preview open roles from the committed OpenOppsDB snapshot.",
	},
};

export default function HomePage() {
	return (
		<Suspense
			fallback={
				<div className="opps-loading mx-auto my-8 min-h-[24rem] max-w-[96rem]">
					Loading open jobs index...
				</div>
			}
		>
			<JobsBoard />
		</Suspense>
	);
}
