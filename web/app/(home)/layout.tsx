import { HomeLayout } from "fumadocs-ui/layouts/home";
import { NuqsAdapter } from "nuqs/adapters/next/app";

import { baseOptions } from "@/lib/layout.shared";

export default function Layout({ children }: LayoutProps<"/">) {
	return (
		<HomeLayout {...baseOptions()}>
			<NuqsAdapter>{children}</NuqsAdapter>
		</HomeLayout>
	);
}
