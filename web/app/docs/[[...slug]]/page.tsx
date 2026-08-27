import { getPageImage, getPageMarkdownUrl, source } from "@/lib/source";
import {
	DocsBody,
	DocsDescription,
	DocsPage,
	DocsTitle,
	MarkdownCopyButton,
	ViewOptionsPopover,
} from "fumadocs-ui/layouts/docs/page";
import { notFound } from "next/navigation";
import { getMDXComponents } from "@/components/mdx";
import type { Metadata } from "next";
import { createRelativeLink } from "fumadocs-ui/mdx";
import { gitConfig } from "@/lib/shared";
import {
	docsJsonLd,
	docsPageMetadata,
	jsonLdScriptProps,
} from "@/lib/site-metadata";

export default async function Page(props: PageProps<"/docs/[[...slug]]">) {
	const params = await props.params;
	const page = source.getPage(params.slug);
	if (!page) notFound();

	const MDX = page.data.body;
	const markdownUrl = getPageMarkdownUrl(page).url;
	const pagePath = page.path.replace(/\.mdx?$/, "");
	const pageKind = pagePath === "index" ? "Start here" : "Reference";

	return (
		<>
			<script
				{...jsonLdScriptProps(
					docsJsonLd({
						title: page.data.title,
						description: page.data.description,
						slug: params.slug,
					}),
				)}
			/>
			<DocsPage toc={page.data.toc} full={page.data.full}>
				<div className="openopps-doc-hero">
					<div>
						<p className="opps-kicker">OpenOpps docs / {pageKind}</p>
						<DocsTitle>{page.data.title}</DocsTitle>
						<DocsDescription className="mb-0">
							{page.data.description}
						</DocsDescription>
					</div>
					<div className="openopps-doc-badges" aria-label="Page traits">
						<span>CLI-only</span>
						<span>local ledger</span>
						<span>{pagePath}</span>
					</div>
				</div>
				<div className="openopps-doc-actions flex flex-row gap-2 items-center border-b pb-6">
					<MarkdownCopyButton markdownUrl={markdownUrl} />
					<ViewOptionsPopover
						markdownUrl={markdownUrl}
						githubUrl={`https://github.com/${gitConfig.user}/${gitConfig.repo}/blob/${gitConfig.branch}/web/content/docs/${page.path}`}
					/>
				</div>
				<DocsBody className="openopps-doc-body">
					<MDX
						components={getMDXComponents({
							// this allows you to link to other pages with relative file paths
							a: createRelativeLink(source, page),
						})}
					/>
				</DocsBody>
			</DocsPage>
		</>
	);
}

export async function generateStaticParams() {
	return source.generateParams();
}

export async function generateMetadata(
	props: PageProps<"/docs/[[...slug]]">,
): Promise<Metadata> {
	const params = await props.params;
	const page = source.getPage(params.slug);
	if (!page) notFound();
	const imageUrl = getPageImage(page).url;

	return docsPageMetadata({
		title: page.data.title,
		description: page.data.description,
		slug: params.slug,
		imageUrl,
		markdownUrl: getPageMarkdownUrl(page).url,
	});
}
