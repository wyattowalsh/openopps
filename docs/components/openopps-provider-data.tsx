import { openOppsData } from "@/lib/openopps-data";
import type { ProviderData } from "@/lib/openopps-data";

const sampleSources = openOppsData.sourceCatalog.slice(0, 12);

function SupportChip({ value }: { value: string }) {
	return (
		<span className="openopps-status-chip" data-tone={value}>
			{value}
		</span>
	);
}

function RouteChip({ detectsRoutes }: { detectsRoutes: boolean }) {
	return (
		<span
			className="openopps-status-chip"
			data-tone={detectsRoutes ? "yes" : "no"}
		>
			{detectsRoutes ? "routes" : "catalog"}
		</span>
	);
}

function ProviderTable({ providers }: { providers: ProviderData[] }) {
	return (
		<div className="openopps-data-table-wrap">
			<table>
				<thead>
					<tr>
						<th>Label</th>
						<th>ID</th>
						<th>Support</th>
						<th>Route role</th>
						<th>Public behavior</th>
					</tr>
				</thead>
				<tbody>
					{providers.map((provider) => (
						<tr key={provider.id}>
							<td>{provider.label}</td>
							<td>
								<code>{provider.id}</code>
							</td>
							<td>
								<SupportChip value={provider.supportLevel} />
							</td>
							<td>
								<RouteChip detectsRoutes={provider.detectsRoutes} />
							</td>
							<td>{provider.description}</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

export function SourceAdapterSummary() {
	return (
		<section
			className="openopps-data-panel"
			aria-labelledby="source-adapters-title"
		>
			<div className="openopps-data-panel-header">
				<div>
					<p className="opps-kicker">Generated adapter inventory</p>
					<h3 id="source-adapters-title" className="openopps-data-panel-title">
						Source adapters
					</h3>
				</div>
				<p className="openopps-data-panel-meta">
					{openOppsData.stats.sourceAdapterCount} adapter ids
				</p>
			</div>
			<p>
				Source adapters discover company boards and preserve provider hints.
				They are detection surfaces; job fetching happens later through
				job-capable provider routes.
			</p>
			<ProviderTable providers={openOppsData.sourceAdapters} />
		</section>
	);
}

export function SourceCatalogSummary() {
	return (
		<section
			className="openopps-data-panel"
			aria-labelledby="source-catalog-title"
		>
			<div className="openopps-data-panel-header">
				<div>
					<p className="opps-kicker">Packaged source catalog</p>
					<h3 id="source-catalog-title" className="openopps-data-panel-title">
						First 12 source records
					</h3>
				</div>
				<p className="openopps-data-panel-meta">
					12 of {openOppsData.stats.sourceRecordCount} records
				</p>
			</div>
			<p>
				The generated table below is a sample of the packaged catalog. Use{" "}
				<code>uv run openopps sources list --json</code> for the full local,
				machine-readable inventory.
			</p>
			<div className="openopps-data-table-wrap">
				<table>
					<thead>
						<tr>
							<th>Source key</th>
							<th>Adapter</th>
							<th>Type</th>
							<th>Access</th>
							<th>Catalog URL</th>
						</tr>
					</thead>
					<tbody>
						{sampleSources.map((source) => (
							<tr key={source.key}>
								<td>
									<code>{source.key}</code>
								</td>
								<td>
									<code>{source.providerId}</code>
								</td>
								<td>{source.taxonomy.providerType ?? "source"}</td>
								<td>{source.taxonomy.accessType ?? "public"}</td>
								<td>
									<a href={source.url}>{source.url}</a>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</section>
	);
}

export function JobProviderSummary() {
	return (
		<section
			className="openopps-data-panel"
			aria-labelledby="job-providers-title"
		>
			<div className="openopps-data-panel-header">
				<div>
					<p className="opps-kicker">Generated provider registry</p>
					<h3 id="job-providers-title" className="openopps-data-panel-title">
						Job-capable providers
					</h3>
				</div>
				<p className="openopps-data-panel-meta">
					{openOppsData.stats.jobProviderCount} job-ready adapters
				</p>
			</div>
			<ProviderTable providers={openOppsData.jobProviders} />
		</section>
	);
}

export function AuditProviderTargets() {
	return (
		<section
			className="openopps-data-panel"
			aria-labelledby="audit-targets-title"
		>
			<div className="openopps-data-panel-header">
				<div>
					<p className="opps-kicker">Provider adoption audit</p>
					<h3 id="audit-targets-title" className="openopps-data-panel-title">
						Candidate provider targets
					</h3>
				</div>
				<p className="openopps-data-panel-meta">
					{openOppsData.auditProviderTargets.length} audit surfaces
				</p>
			</div>
			<p>
				<code>providers audit</code> reports persisted-board evidence for{" "}
				{openOppsData.auditProviderTargets.map((provider, index) => (
					<span key={provider}>
						<code>{provider}</code>
						{index === openOppsData.auditProviderTargets.length - 1
							? "."
							: ", "}
					</span>
				))}{" "}
				It includes candidate route and board counts, example boards, and
				do-not-adopt rationales for providers that do not yet have reliable
				generic public fetching in v0.1.
			</p>
		</section>
	);
}
