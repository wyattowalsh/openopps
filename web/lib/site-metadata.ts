import type { Metadata } from "next";

import { serializeJsonLdScript } from "@/lib/job-detail-utils";
import { appName, siteUrl, socialImages } from "@/lib/shared";

export const HOME_PATH = "/";
export const EXPLORER_PATH = "/explorer";
export const DOCS_PATH = "/docs";
export const FEED_PATH = "/feed.xml";
export const LLMS_TXT_PATH = "/llms.txt";
export const LLMS_FULL_TXT_PATH = "/llms-full.txt";
export const KAGGLE_DATASET_URL =
	"https://www.kaggle.com/datasets/wyattowalsh/openoppsdb";

export const siteWideCopy = {
	description:
		"OpenOpps is a public hiring snapshot: browse the latest open jobs, inspect coverage in Explorer, and read CLI documentation.",
} as const;

export const homePageCopy = {
	title: "Jobs board",
	description:
		"Browse the latest open jobs from the OpenOpps public hiring snapshot. Search and preview open roles from the committed OpenOppsDB index.",
} as const;

export const explorerPageCopy = {
	title: "Explorer",
	description:
		"Dashboard for OpenOppsDB snapshot coverage, data quality, route health, latest open jobs, and row inspection.",
} as const;

export const docsIndexCopy = {
	title: "Docs",
	description:
		"OpenOpps concepts, CLI commands, public hiring snapshot surfaces, and contributor documentation.",
} as const;

type SocialImage = {
	url: string;
	width: number;
	height: number;
	alt: string;
};

type PageMetadataInput = {
	title: string;
	description: string;
	pathname: string;
	ogType?: "website" | "article";
	ogTitle?: string;
	twitterTitle?: string;
	image?: SocialImage;
	markdownUrl?: string;
	atomUrl?: string;
};

type BreadcrumbItem = {
	name: string;
	pathname: string;
};

export function canonicalSiteUrl(pathname = HOME_PATH): string {
	if (pathname === HOME_PATH || pathname === "") {
		return siteUrl;
	}
	const normalized = pathname.startsWith("/") ? pathname : `/${pathname}`;
	return `${siteUrl}${normalized.replace(/\/+$/, "")}`;
}

export function describedbyLlmsUrl() {
	return canonicalSiteUrl(LLMS_TXT_PATH);
}

export function jobsFeedUrl() {
	return canonicalSiteUrl(FEED_PATH);
}

function absoluteAssetUrl(path: string) {
	if (path.startsWith("http://") || path.startsWith("https://")) {
		return path;
	}
	return canonicalSiteUrl(path);
}

export function buildPageMetadata({
	title,
	description,
	pathname,
	ogType = "website",
	ogTitle,
	twitterTitle,
	image,
	markdownUrl,
	atomUrl,
}: PageMetadataInput): Metadata {
	const url = canonicalSiteUrl(pathname);
	const socialImage: SocialImage = image ?? {
		url: socialImages.repository,
		width: 1200,
		height: 630,
		alt: `${appName} open-door social card`,
	};
	const titled = `${title} | ${appName}`;
	const types: Record<string, string> = {};
	if (markdownUrl) {
		types["text/markdown"] = absoluteAssetUrl(markdownUrl);
	}
	if (atomUrl) {
		types["application/atom+xml"] = absoluteAssetUrl(atomUrl);
	}
	return {
		title,
		description,
		alternates: {
			canonical: url,
			...(Object.keys(types).length > 0 ? { types } : {}),
		},
		openGraph: {
			title: ogTitle ?? titled,
			description,
			url,
			siteName: appName,
			type: ogType,
			images: [socialImage],
		},
		twitter: {
			card: "summary_large_image",
			title: twitterTitle ?? titled,
			description,
			images: [socialImage.url],
		},
	};
}

export function homePageMetadata(): Metadata {
	return buildPageMetadata({
		title: homePageCopy.title,
		description: homePageCopy.description,
		pathname: HOME_PATH,
		atomUrl: jobsFeedUrl(),
		image: {
			url: socialImages.database,
			width: 1200,
			height: 630,
			alt: `${appName} jobs snapshot`,
		},
	});
}

export function explorerPageMetadata(): Metadata {
	return buildPageMetadata({
		title: explorerPageCopy.title,
		description: explorerPageCopy.description,
		pathname: EXPLORER_PATH,
		image: {
			url: socialImages.database,
			width: 1200,
			height: 630,
			alt: `${appName} jobs snapshot`,
		},
	});
}

export function docsIndexMetadata(): Metadata {
	return buildPageMetadata({
		title: docsIndexCopy.title,
		description: docsIndexCopy.description,
		pathname: DOCS_PATH,
		ogType: "article",
		ogTitle: docsIndexCopy.title,
		twitterTitle: docsIndexCopy.title,
		markdownUrl: "/llms.mdx/docs/content.md",
	});
}

export function docsPageMetadata(input: {
	title: string;
	description?: string;
	slug?: string[] | undefined;
	imageUrl: string;
	markdownUrl?: string;
}): Metadata {
	const slug = (input.slug ?? []).filter(Boolean).join("/");
	const pathname = slug ? `${DOCS_PATH}/${slug}` : DOCS_PATH;
	const description = input.description?.trim() || docsIndexCopy.description;
	return buildPageMetadata({
		title: input.title,
		description,
		pathname,
		ogType: "article",
		ogTitle: input.title,
		twitterTitle: input.title,
		markdownUrl: input.markdownUrl,
		image: {
			url: input.imageUrl,
			width: 1200,
			height: 630,
			alt: `${input.title} documentation social card`,
		},
	});
}

export function organizationJsonLd() {
	return {
		"@type": "Organization",
		name: appName,
		url: siteUrl,
		logo: absoluteAssetUrl("/brand/openopps-logo.png"),
	};
}

export function datasetJsonLd() {
	return {
		"@type": "Dataset",
		name: "OpenOppsDB",
		description: explorerPageCopy.description,
		url: canonicalSiteUrl(EXPLORER_PATH),
		sameAs: KAGGLE_DATASET_URL,
		isAccessibleForFree: true,
		creator: organizationJsonLd(),
		license: "https://creativecommons.org/publicdomain/zero/1.0/",
	};
}

export function breadcrumbJsonLd(items: BreadcrumbItem[]) {
	return {
		"@type": "BreadcrumbList",
		itemListElement: items.map((item, index) => ({
			"@type": "ListItem",
			position: index + 1,
			name: item.name,
			item: canonicalSiteUrl(item.pathname),
		})),
	};
}

export function homeJsonLd() {
	return {
		"@context": "https://schema.org",
		"@graph": [
			{
				"@type": "WebSite",
				name: appName,
				url: siteUrl,
				description: homePageCopy.description,
				inLanguage: "en",
				publisher: organizationJsonLd(),
				potentialAction: {
					"@type": "SearchAction",
					target: {
						"@type": "EntryPoint",
						urlTemplate: `${siteUrl}/?q={search_term_string}`,
					},
					"query-input": "required name=search_term_string",
				},
			},
			organizationJsonLd(),
			datasetJsonLd(),
			breadcrumbJsonLd([{ name: homePageCopy.title, pathname: HOME_PATH }]),
		],
	};
}

export function explorerJsonLd() {
	const url = canonicalSiteUrl(EXPLORER_PATH);
	return {
		"@context": "https://schema.org",
		"@graph": [
			{
				"@type": "WebApplication",
				name: `${explorerPageCopy.title} | ${appName}`,
				url,
				description: explorerPageCopy.description,
				applicationCategory: "BusinessApplication",
				operatingSystem: "Any",
				isAccessibleForFree: true,
				publisher: organizationJsonLd(),
			},
			organizationJsonLd(),
			datasetJsonLd(),
			breadcrumbJsonLd([
				{ name: homePageCopy.title, pathname: HOME_PATH },
				{ name: explorerPageCopy.title, pathname: EXPLORER_PATH },
			]),
		],
	};
}

export function docsJsonLd(input: {
	title: string;
	description?: string;
	slug?: string[] | undefined;
}) {
	const slug = (input.slug ?? []).filter(Boolean).join("/");
	const pathname = slug ? `${DOCS_PATH}/${slug}` : DOCS_PATH;
	const url = canonicalSiteUrl(pathname);
	const description = input.description?.trim() || docsIndexCopy.description;
	const crumbs: BreadcrumbItem[] = [
		{ name: homePageCopy.title, pathname: HOME_PATH },
		{ name: docsIndexCopy.title, pathname: DOCS_PATH },
	];
	if (slug) {
		crumbs.push({ name: input.title, pathname });
	}
	return {
		"@context": "https://schema.org",
		"@graph": [
			{
				"@type": "TechArticle",
				headline: input.title,
				name: input.title,
				description,
				url,
				mainEntityOfPage: url,
				isAccessibleForFree: true,
				author: organizationJsonLd(),
				publisher: organizationJsonLd(),
			},
			breadcrumbJsonLd(crumbs),
		],
	};
}

export function jobBreadcrumbJsonLd(input: { title: string; jobId: string }) {
	return {
		"@context": "https://schema.org",
		"@graph": [
			breadcrumbJsonLd([
				{ name: homePageCopy.title, pathname: HOME_PATH },
				{
					name: input.title,
					pathname: `/jobs/${encodeURIComponent(input.jobId)}`,
				},
			]),
		],
	};
}

export function jsonLdScriptProps(value: unknown) {
	return {
		type: "application/ld+json" as const,
		dangerouslySetInnerHTML: {
			__html: serializeJsonLdScript(value),
		},
	};
}
