import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";
import { OpenOppsSearchExplorer } from "@/components/openopps-search-explorer";
import {
	AuditProviderTargets,
	JobProviderSummary,
	SourceAdapterSummary,
	SourceCatalogSummary,
} from "@/components/openopps-provider-data";
import type { MDXComponents } from "mdx/types";

export function getMDXComponents(components?: MDXComponents) {
	return {
		...defaultMdxComponents,
		AuditProviderTargets,
		JobProviderSummary,
		Mermaid,
		OpenOppsSearchExplorer,
		SourceAdapterSummary,
		SourceCatalogSummary,
		...components,
	} satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
	type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
