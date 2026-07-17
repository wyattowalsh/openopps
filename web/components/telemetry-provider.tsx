"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import type { PostHogConfig } from "posthog-js";
import {
	collectBrowserTelemetryContext,
	flushTelemetry,
	installTelemetryLifecycleHandlers,
	setTelemetryRouteContext,
	trackTelemetry,
} from "@/lib/telemetry";

const POSTHOG_DEFAULT_HOST = "https://us.i.posthog.com";

let postHogInitPromise: Promise<void> | undefined;
type PageEngagementReason = "route_change" | "unmount" | "visibility_hidden";

export function TelemetryProvider({ children }: { children: ReactNode }) {
	const pathname = usePathname();
	const currentPathRef = useRef<string | undefined>(undefined);
	const startedAtRef = useRef(0);
	const visibleStartedAtRef = useRef<number | undefined>(undefined);
	const visibleDurationMsRef = useRef(0);
	const interactionCountRef = useRef(0);
	const lastEmittedDurationMsRef = useRef(0);
	const lastEmittedInteractionCountRef = useRef(0);
	const lastEmittedVisibleDurationMsRef = useRef(0);
	const engagementSequenceRef = useRef(0);

	const trackPageEngagement = useCallback((reason: PageEngagementReason) => {
		const path = currentPathRef.current;
		const startedAt = startedAtRef.current;
		if (!path || startedAt <= 0) {
			return;
		}
		const timestamp = now();
		if (visibleStartedAtRef.current !== undefined) {
			visibleDurationMsRef.current += Math.max(
				0,
				timestamp - visibleStartedAtRef.current,
			);
			visibleStartedAtRef.current =
				typeof document !== "undefined" && document.visibilityState === "visible"
					? timestamp
					: undefined;
		}
		const durationMs = Math.max(0, timestamp - startedAt);
		const visibleDurationMs = visibleDurationMsRef.current;
		const interactionCount = interactionCountRef.current;
		const durationDeltaMs = Math.max(
			0,
			durationMs - lastEmittedDurationMsRef.current,
		);
		const visibleDurationDeltaMs = Math.max(
			0,
			visibleDurationMs - lastEmittedVisibleDurationMsRef.current,
		);
		const interactionDeltaCount = Math.max(
			0,
			interactionCount - lastEmittedInteractionCountRef.current,
		);
		if (
			durationDeltaMs === 0 &&
			visibleDurationDeltaMs === 0 &&
			interactionDeltaCount === 0
		) {
			return;
		}
		engagementSequenceRef.current += 1;
		lastEmittedDurationMsRef.current = durationMs;
		lastEmittedVisibleDurationMsRef.current = visibleDurationMs;
		lastEmittedInteractionCountRef.current = interactionCount;
		trackTelemetry("page_engagement", {
			durationDeltaMs: Math.round(durationDeltaMs),
			durationMs: Math.round(durationMs),
			interactionCount,
			interactionDeltaCount,
			path,
			reason,
			sequence: engagementSequenceRef.current,
			visibleDurationDeltaMs: Math.round(visibleDurationDeltaMs),
			visibleDurationMs: Math.round(visibleDurationMs),
		});
	}, []);

	useEffect(() => {
		void initializePostHogBrowserClient();
		return installTelemetryLifecycleHandlers();
	}, []);

	useEffect(() => {
		const recordInteraction = () => {
			interactionCountRef.current += 1;
		};
		window.addEventListener("click", recordInteraction, { passive: true });
		window.addEventListener("keydown", recordInteraction);
		window.addEventListener("pointerdown", recordInteraction, {
			passive: true,
		});
		return () => {
			window.removeEventListener("click", recordInteraction);
			window.removeEventListener("keydown", recordInteraction);
			window.removeEventListener("pointerdown", recordInteraction);
		};
	}, []);

	useEffect(() => {
		trackPageEngagement("route_change");
		const context = collectBrowserTelemetryContext();
		setTelemetryRouteContext(context);
		trackTelemetry("page_view", {
			path: context.path,
			title: context.title,
		});
		currentPathRef.current = context.path;
		startedAtRef.current = now();
		visibleStartedAtRef.current =
			typeof document !== "undefined" && document.visibilityState === "visible"
				? startedAtRef.current
				: undefined;
		visibleDurationMsRef.current = 0;
		interactionCountRef.current = 0;
		lastEmittedDurationMsRef.current = 0;
		lastEmittedInteractionCountRef.current = 0;
		lastEmittedVisibleDurationMsRef.current = 0;
		engagementSequenceRef.current = 0;
	}, [pathname, trackPageEngagement]);

	useEffect(() => {
		const onVisibilityChange = () => {
			if (document.visibilityState === "hidden") {
				trackPageEngagement("visibility_hidden");
				void flushTelemetry("visibility_hidden_engagement");
				return;
			}
			visibleStartedAtRef.current = now();
		};
		document.addEventListener("visibilitychange", onVisibilityChange);
		return () => {
			trackPageEngagement("unmount");
			document.removeEventListener("visibilitychange", onVisibilityChange);
		};
	}, [trackPageEngagement]);

	return children;
}

async function initializePostHogBrowserClient() {
	if (postHogInitPromise) {
		return postHogInitPromise;
	}
	postHogInitPromise = initializePostHogBrowserClientOnce();
	return postHogInitPromise;
}

async function initializePostHogBrowserClientOnce() {
	if (
		typeof window === "undefined" ||
		!readPublicBoolean("NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED") ||
		readPublicBoolean("NEXT_PUBLIC_OPENOPPS_ANALYTICS_DISABLED") ||
		readPublicBoolean("NEXT_PUBLIC_OPENOPPS_TELEMETRY_DISABLED")
	) {
		return;
	}
	const projectApiKey = readPublicString(
		"NEXT_PUBLIC_OPENOPPS_POSTHOG_PROJECT_API_KEY",
	);
	if (!projectApiKey) {
		return;
	}
	const { default: posthog } = await import("posthog-js");
	if (posthog.__loaded) {
		return;
	}
	const config = {
		api_host:
			readPublicString("NEXT_PUBLIC_OPENOPPS_POSTHOG_HOST") ??
			POSTHOG_DEFAULT_HOST,
		autocapture: false,
		capture_pageleave: false,
		capture_pageview: false,
		session_recording: {
			blockSelector:
				"[data-openopps-private], [data-telemetry-private], [data-sensitive]",
			maskAllInputs: true,
			maskTextSelector: "*",
			recordBody: false,
			recordHeaders: false,
		},
	} satisfies Partial<PostHogConfig>;
	posthog.init(projectApiKey, config);
	if (readPublicBoolean("NEXT_PUBLIC_OPENOPPS_POSTHOG_RECORDING")) {
		posthog.startSessionRecording();
	}
}

function readPublicString(name: string) {
	if (typeof process === "undefined") {
		return undefined;
	}
	return process.env?.[name];
}

function readPublicBoolean(name: string) {
	const value = readPublicString(name);
	return value === "1" || value === "true" || value === "yes";
}

function now() {
	return typeof performance !== "undefined" ? performance.now() : Date.now();
}
