import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

import { appName } from "@/lib/shared";

const JobsBoard = dynamic(
	() =>
		import("@/components/jobs-board/jobs-board").then((module) => ({
			default: module.JobsBoard,
		})),
	{
		loading: () => (
			<div
				className="opps-loading mx-auto my-8 min-h-[24rem] max-w-[96rem]"
				role="status"
				aria-live="polite"
				aria-busy="true"
			>
				<Loader2 className="size-4 animate-spin" aria-hidden="true" />
				Loading open jobs index...
			</div>
		),
	},
);

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
	return <JobsBoard />;
}
