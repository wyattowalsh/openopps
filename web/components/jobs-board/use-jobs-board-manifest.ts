"use client";

import { useEffect, useState } from "react";

import { loadSearchManifest } from "@/components/openopps-search/search-index-loader";
import type { SearchManifest } from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { searchManifestFromChrome, type SnapshotChrome } from "@/lib/snapshot-chrome";
import { trackTelemetry } from "@/lib/telemetry";

export function useJobsBoardManifest(chrome: SnapshotChrome | null = null) {
	const [manifest, setManifest] = useState<SearchManifest | null>(() =>
		chrome ? searchManifestFromChrome(chrome) : null,
	);
	const [loading, setLoading] = useState(!chrome);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let mounted = true;
		const startLoad = () => {
			void (async () => {
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
			})();
		};

		if (!chrome) {
			startLoad();
			return () => {
				mounted = false;
			};
		}

		if (typeof requestIdleCallback === "function") {
			const idleId = requestIdleCallback(startLoad, { timeout: 1800 });
			return () => {
				mounted = false;
				cancelIdleCallback(idleId);
			};
		}
		const timeoutId = window.setTimeout(startLoad, 0);
		return () => {
			mounted = false;
			window.clearTimeout(timeoutId);
		};
	}, [chrome]);

	return { manifest, loading, error, setError };
}
