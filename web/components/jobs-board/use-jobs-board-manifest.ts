"use client";

import { useEffect, useState } from "react";

import { loadSearchManifest } from "@/components/openopps-search/search-index-loader";
import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { trackTelemetry } from "@/lib/telemetry";

export function useJobsBoardManifest() {
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let mounted = true;

		async function load() {
			try {
				const nextManifest = await loadSearchManifest();
				if (mounted) {
					setManifest(nextManifest);
					setError(null);
					trackTelemetry("jobs.index_loaded", {
						initialRows: 0,
						totalRows: nextManifest.entities.jobs.count,
						manifestVersion: nextManifest.version,
					});
				}
			} catch (caught) {
				if (mounted) {
					const message = formatLoadError(caught);
					setError(message);
					trackTelemetry("jobs.index_error", { message });
				}
			} finally {
				if (mounted) {
					setLoading(false);
				}
			}
		}

		void load();
		return () => {
			mounted = false;
		};
	}, []);

	return { manifest, loading, error, setError };
}