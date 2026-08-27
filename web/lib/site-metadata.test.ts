import { describe, expect, it } from "vitest";

import { serializeJsonLdScript } from "@/lib/job-detail-utils";
import { appName, siteUrl, socialImages } from "@/lib/shared";
import {
	breadcrumbJsonLd,
	canonicalSiteUrl,
	datasetJsonLd,
	describedbyLlmsUrl,
	docsIndexCopy,
	docsIndexMetadata,
	docsJsonLd,
	docsPageMetadata,
	explorerJsonLd,
	explorerPageCopy,
	explorerPageMetadata,
	homeJsonLd,
	homePageCopy,
	homePageMetadata,
	jobBreadcrumbJsonLd,
	jobsFeedUrl,
	jsonLdScriptProps,
	organizationJsonLd,
	siteWideCopy,
} from "@/lib/site-metadata";

describe("site-metadata", () => {
	it("pins the canonical host to the live www origin", () => {
		expect(siteUrl).toBe("https://www.openopps.dev");
		expect(siteWideCopy.description.toLowerCase()).not.toContain(
			"developer documentation",
		);
	});

	it("mentions latest open jobs in the home description helper", () => {
		expect(homePageCopy.description.toLowerCase()).toContain("latest open jobs");
		expect(homePageMetadata().description).toBe(homePageCopy.description);
		expect(homePageMetadata().alternates).toMatchObject({
			canonical: siteUrl,
			types: {
				"application/atom+xml": jobsFeedUrl(),
			},
		});
	});

	it("builds absolute canonical urls without a trailing slash", () => {
		expect(canonicalSiteUrl("/")).toBe(siteUrl);
		expect(canonicalSiteUrl("")).toBe(siteUrl);
		expect(canonicalSiteUrl("/explorer")).toBe(`${siteUrl}/explorer`);
		expect(canonicalSiteUrl("/docs/cli/")).toBe(`${siteUrl}/docs/cli`);
	});

	it("gives explorer unique canonical, OG, and Twitter fields", () => {
		const metadata = explorerPageMetadata();
		const canonical = `${siteUrl}/explorer`;
		expect(metadata.title).toBe(explorerPageCopy.title);
		expect(metadata.description).toBe(explorerPageCopy.description);
		expect(metadata.alternates).toEqual({ canonical });
		expect(metadata.openGraph).toMatchObject({
			title: `${explorerPageCopy.title} | ${appName}`,
			description: explorerPageCopy.description,
			url: canonical,
			siteName: appName,
			type: "website",
		});
		expect(metadata.openGraph?.images).toEqual([
			{
				url: socialImages.database,
				width: 1200,
				height: 630,
				alt: `${appName} jobs snapshot`,
			},
		]);
		expect(metadata.twitter).toMatchObject({
			card: "summary_large_image",
			title: `${explorerPageCopy.title} | ${appName}`,
			description: explorerPageCopy.description,
			images: [socialImages.database],
		});
		expect(String(metadata.twitter?.description)).not.toMatch(
			/developer documentation/i,
		);
	});

	it("adds docs canonical URLs, markdown alternates, and keeps page titles on OG and Twitter", () => {
		const index = docsIndexMetadata();
		expect(index.alternates).toEqual({
			canonical: `${siteUrl}/docs`,
			types: {
				"text/markdown": `${siteUrl}/llms.mdx/docs/content.md`,
			},
		});
		expect(index.openGraph).toMatchObject({
			title: docsIndexCopy.title,
			url: `${siteUrl}/docs`,
			siteName: appName,
			type: "article",
		});

		const cli = docsPageMetadata({
			title: "CLI",
			description: "Command groups for the OpenOpps CLI.",
			slug: ["cli"],
			imageUrl: "/og/docs/cli/image.png",
			markdownUrl: "/llms.mdx/docs/cli/content.md",
		});
		expect(cli.alternates).toEqual({
			canonical: `${siteUrl}/docs/cli`,
			types: {
				"text/markdown": `${siteUrl}/llms.mdx/docs/cli/content.md`,
			},
		});
		expect(cli.openGraph).toMatchObject({
			title: "CLI",
			description: "Command groups for the OpenOpps CLI.",
			url: `${siteUrl}/docs/cli`,
			siteName: appName,
			type: "article",
		});
		expect(cli.twitter).toMatchObject({
			title: "CLI",
			description: "Command groups for the OpenOpps CLI.",
			images: ["/og/docs/cli/image.png"],
		});
	});

	it("emits SearchAction, Organization, Dataset, and BreadcrumbList without script breakouts", () => {
		const home = homeJsonLd();
		expect(home["@graph"]).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					"@type": "WebSite",
					url: siteUrl,
					description: homePageCopy.description,
					potentialAction: expect.objectContaining({
						"@type": "SearchAction",
						target: expect.objectContaining({
							urlTemplate: `${siteUrl}/?q={search_term_string}`,
						}),
					}),
				}),
				expect.objectContaining({
					"@type": "Organization",
					name: appName,
					url: siteUrl,
				}),
				expect.objectContaining({
					"@type": "Dataset",
					sameAs: "https://www.kaggle.com/datasets/wyattowalsh/openoppsdb",
				}),
				expect.objectContaining({ "@type": "BreadcrumbList" }),
			]),
		);
		expect(JSON.stringify(home)).not.toContain("/api/jobs/search");

		const explorer = explorerJsonLd();
		expect(explorer["@graph"]).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					"@type": "WebApplication",
					url: `${siteUrl}/explorer`,
				}),
				expect.objectContaining({ "@type": "Dataset" }),
				expect.objectContaining({ "@type": "BreadcrumbList" }),
			]),
		);

		const docs = docsJsonLd({ title: "Start Here", slug: [] });
		expect(docs["@graph"]).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					"@type": "TechArticle",
					headline: "Start Here",
					url: `${siteUrl}/docs`,
				}),
				expect.objectContaining({ "@type": "BreadcrumbList" }),
			]),
		);

		expect(organizationJsonLd().name).toBe(appName);
		expect(datasetJsonLd().url).toBe(`${siteUrl}/explorer`);
		expect(breadcrumbJsonLd([{ name: "Jobs", pathname: "/" }]).itemListElement[0]).toMatchObject({
			position: 1,
			item: siteUrl,
		});
		expect(jobBreadcrumbJsonLd({ title: "Engineer", jobId: "abc" })["@graph"][0]).toMatchObject({
			"@type": "BreadcrumbList",
		});
		expect(describedbyLlmsUrl()).toBe(`${siteUrl}/llms.txt`);

		const malicious = docsJsonLd({
			title: "</script><script>alert(1)</script>",
			description: "Safe body",
			slug: ["cli"],
		});
		const serialized = serializeJsonLdScript(malicious);
		expect(serialized).not.toContain("</script>");
		expect(jsonLdScriptProps(malicious).dangerouslySetInnerHTML.__html).toBe(
			serialized,
		);
	});
});
