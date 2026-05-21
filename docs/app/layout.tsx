import { RootProvider } from "fumadocs-ui/provider/next";
import "./global.css";
import { appName, gitConfig } from "@/lib/shared";
import type { Metadata } from "next";

const siteUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;
const siteDescription =
	"Developer documentation for the OpenOpps CLI, providers, route diagnostics, storage, and exports.";

export const metadata: Metadata = {
	metadataBase: new URL(siteUrl),
	applicationName: appName,
	title: {
		default: appName,
		template: `%s | ${appName}`,
	},
	description: siteDescription,
	manifest: "/site.webmanifest",
	icons: {
		icon: [
			{ url: "/favicon.ico", sizes: "any" },
			{ url: "/favicons/favicon-16x16.png", sizes: "16x16", type: "image/png" },
			{ url: "/favicons/favicon-32x32.png", sizes: "32x32", type: "image/png" },
			{ url: "/favicons/favicon-48x48.png", sizes: "48x48", type: "image/png" },
		],
		apple: [
			{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
		],
		shortcut: ["/favicon.ico"],
	},
	appleWebApp: {
		title: appName,
		capable: true,
		statusBarStyle: "default",
	},
	openGraph: {
		title: appName,
		description:
			"Discover aggregate hiring boards, detect provider routes, and sync public job postings.",
		url: siteUrl,
		siteName: appName,
		images: [
			{
				url: "/og-image.png",
				width: 1200,
				height: 630,
				alt: `${appName} logo`,
			},
		],
	},
	twitter: {
		card: "summary_large_image",
		title: appName,
		description: siteDescription,
		images: ["/og-image.png"],
	},
};

export default function Layout({ children }: LayoutProps<"/">) {
	return (
		<html lang="en" suppressHydrationWarning>
			<body className="flex min-h-screen flex-col">
				<RootProvider>{children}</RootProvider>
			</body>
		</html>
	);
}
