"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import {
	collectBrowserTelemetryContext,
	installTelemetryLifecycleHandlers,
	setTelemetryRouteContext,
	trackTelemetry,
} from "@/lib/telemetry";

export function TelemetryProvider({ children }: { children: ReactNode }) {
	const pathname = usePathname();

	useEffect(() => {
		return installTelemetryLifecycleHandlers();
	}, []);

	useEffect(() => {
		const context = collectBrowserTelemetryContext();
		setTelemetryRouteContext(context);
		trackTelemetry("page_view", {
			path: context.path,
			title: context.title,
		});
	}, [pathname]);

	return children;
}
