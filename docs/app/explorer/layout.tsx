import { HomeLayout } from "fumadocs-ui/layouts/home";
import { NuqsAdapter } from "nuqs/adapters/next/app";

import { baseOptions } from "@/lib/layout.shared";

export default function ExplorerLayout({
	children,
}: LayoutProps<"/explorer">) {
	return (
		<HomeLayout {...baseOptions()}>
			<NuqsAdapter>{children}</NuqsAdapter>
		</HomeLayout>
	);
}
