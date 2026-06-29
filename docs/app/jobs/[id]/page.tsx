import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { JobsBoard } from "@/components/jobs-board/jobs-board";
import { appName } from "@/lib/shared";

type JobDeepLinkPageProps = {
	params: Promise<{ id: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({
	params,
}: {
	params: Promise<{ id: string }>;
}): Promise<Metadata> {
	const { id } = await params;
	return {
		title: `Job ${id}`,
		description: `Open role preview for job ${id} on the ${appName} jobs board.`,
	};
}

export default async function JobDeepLinkPage({
	params,
	searchParams,
}: JobDeepLinkPageProps) {
	const { id } = await params;
	const query = await searchParams;

	if (Object.keys(query).length === 0) {
		redirect(`/jobs?job=${encodeURIComponent(id)}`);
	}

	return <JobsBoard initialJobId={id} />;
}