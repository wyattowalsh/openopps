import data from "./generated/openopps-data.json";

export type ProviderData = {
	id: string;
	label: string;
	kind: string;
	supportLevel: string;
	description: string;
	detectsRoutes: boolean;
};

export type SourceCatalogEntry = {
	key: string;
	providerId: string;
	url: string;
	taxonomy: {
		providerType?: string;
		coverageMode?: string;
		accessType?: string;
		licenseStatus?: string;
		refreshCadence?: string;
		sourceYear?: number;
		sourceCategory?: string;
		sourceAttribution?: string;
		inclusionReason?: string;
	};
};

export type OpenOppsDocsData = {
	stats: {
		sourceRecordCount: number;
		sourceAdapterCount: number;
		jobProviderCount: number;
		exportFormatCount: number;
	};
	sourceAdapters: ProviderData[];
	jobProviders: ProviderData[];
	sourceCatalog: SourceCatalogEntry[];
	auditProviderTargets: string[];
	exportFormats: string[];
};

export const openOppsData = data as OpenOppsDocsData;

export const sourceStats = [
	["sources", String(openOppsData.stats.sourceRecordCount), "packaged records"],
	[
		"providers",
		String(openOppsData.stats.jobProviderCount),
		"job-ready adapters",
	],
	[
		"exports",
		String(openOppsData.stats.exportFormatCount),
		openOppsData.exportFormats.join("/"),
	],
] as const;
