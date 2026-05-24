import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";
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
		SourceAdapterSummary,
		SourceCatalogSummary,
		...components,
	} satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
	type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
