import { RootProvider } from "fumadocs-ui/provider/next";
import "./global.css";
import { TelemetryProvider } from "@/components/telemetry-provider";
import { shouldNoIndexDeployment } from "@/lib/job-detail-utils";
import { appName, siteUrl, socialImages } from "@/lib/shared";
import {
	describedbyLlmsUrl,
	jobsFeedUrl,
	siteWideCopy,
} from "@/lib/site-metadata";
import type { Metadata } from "next";

const body400Woff2 = new URL(
	"../node_modules/@fontsource/monaspace-neon/files/monaspace-neon-latin-400-normal.woff2",
	import.meta.url,
);
const heading600Woff2 = new URL(
	"../node_modules/@fontsource/monaspace-argon/files/monaspace-argon-latin-600-normal.woff2",
	import.meta.url,
);

export const metadata: Metadata = {
	metadataBase: new URL(siteUrl),
	applicationName: appName,
	title: {
		default: appName,
		template: `%s | ${appName}`,
	},
	description: siteWideCopy.description,
	robots: shouldNoIndexDeployment()
		? {
				index: false,
				follow: false,
			}
		: {
				index: true,
				follow: true,
			},
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
		description: siteWideCopy.description,
		url: siteUrl,
		siteName: appName,
		images: [
			{
				url: socialImages.repository,
				width: 1200,
				height: 630,
				alt: `${appName} open-door social card`,
			},
		],
	},
	twitter: {
		card: "summary_large_image",
		title: appName,
		description: siteWideCopy.description,
		images: [socialImages.repository],
	},
};

export default function Layout({ children }: LayoutProps<"/">) {
	return (
		<html lang="en" suppressHydrationWarning>
			<link
				rel="preload"
				href={body400Woff2.href}
				as="font"
				type="font/woff2"
				crossOrigin="anonymous"
				fetchPriority="high"
			/>
			<link
				rel="preload"
				href={heading600Woff2.href}
				as="font"
				type="font/woff2"
				crossOrigin="anonymous"
				fetchPriority="high"
			/>
			<link rel="describedby" href={describedbyLlmsUrl()} />
			<link
				rel="alternate"
				type="application/atom+xml"
				title="OpenOpps latest open jobs"
				href={jobsFeedUrl()}
			/>
			<body className="flex min-h-screen flex-col">
				<RootProvider search={{ preload: false }}>
					<TelemetryProvider>{children}</TelemetryProvider>
				</RootProvider>
			</body>
		</html>
	);
}
