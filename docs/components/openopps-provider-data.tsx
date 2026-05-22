import { openOppsData } from "@/lib/openopps-data";

const sampleSources = openOppsData.sourceCatalog.slice(0, 12);

export function SourceCatalogSummary() {
	return (
		<>
			<p>
				OpenOpps ships {openOppsData.stats.sourceRecordCount} packaged source
				records across {openOppsData.stats.sourceAdapterCount} source adapter
				ids. The generated table below shows the first 12 source records by
				source key; use <code>uv run openopps sources list --json</code> for the
				full local, machine-readable catalog.
			</p>
			<table>
				<thead>
					<tr>
						<th>Source key</th>
						<th>Adapter</th>
						<th>Status</th>
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
							<td>{source.enabled ? "enabled" : "disabled"}</td>
						</tr>
					))}
				</tbody>
			</table>
		</>
	);
}

export function JobProviderSummary() {
	return (
		<table>
			<thead>
				<tr>
					<th>Provider</th>
					<th>Support</th>
					<th>Public route behavior</th>
				</tr>
			</thead>
			<tbody>
				{openOppsData.jobProviders.map((provider) => (
					<tr key={provider.id}>
						<td>
							<code>{provider.id}</code>
						</td>
						<td>
							<code>{provider.supportLevel}</code>
						</td>
						<td>{provider.description}</td>
					</tr>
				))}
			</tbody>
		</table>
	);
}

export function AuditProviderTargets() {
	return (
		<p>
			<code>providers audit</code> reports persisted-board evidence for{" "}
			{openOppsData.auditProviderTargets.map((provider, index) => (
				<span key={provider}>
					<code>{provider}</code>
					{index === openOppsData.auditProviderTargets.length - 1 ? "." : ", "}
				</span>
			))}
			It includes candidate route and board counts, example boards, and
			do-not-adopt rationales for providers that do not yet have reliable
			generic public fetching in v0.1.
		</p>
	);
}
