// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const navigationMock = vi.hoisted(() => ({
	pathname: "/jobs",
}));

const telemetryMock = vi.hoisted(() => ({
	collectBrowserTelemetryContext: vi.fn(),
	flushTelemetry: vi.fn(),
	installTelemetryLifecycleHandlers: vi.fn(),
	setTelemetryRouteContext: vi.fn(),
	trackTelemetry: vi.fn(),
}));

const posthogMock = vi.hoisted(() => ({
	init: vi.fn(),
	startSessionRecording: vi.fn(),
}));

vi.mock("next/navigation", () => ({
	usePathname: () => navigationMock.pathname,
}));

vi.mock("@/lib/telemetry", () => telemetryMock);

vi.mock("posthog-js", () => ({
	default: {
		__loaded: false,
		init: posthogMock.init,
		startSessionRecording: posthogMock.startSessionRecording,
	},
}));

let currentNow = 10;

beforeEach(() => {
	navigationMock.pathname = "/jobs";
	currentNow = 10;
	setVisibilityState("visible");
	vi.spyOn(performance, "now").mockImplementation(() => currentNow);
	telemetryMock.collectBrowserTelemetryContext.mockImplementation(() => ({
		path: navigationMock.pathname,
		title: "OpenOpps",
	}));
	telemetryMock.flushTelemetry.mockResolvedValue(undefined);
	telemetryMock.installTelemetryLifecycleHandlers.mockReturnValue(vi.fn());
});

afterEach(() => {
	cleanup();
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
	vi.clearAllMocks();
	vi.resetModules();
});

describe("TelemetryProvider", () => {
	it("emits the previous page engagement delta before resetting on route change", async () => {
		const { TelemetryProvider } = await import("./telemetry-provider");
		const view = renderProvider(TelemetryProvider);
		telemetryMock.trackTelemetry.mockClear();

		currentNow = 1010;
		navigationMock.pathname = "/docs";
		view.rerender(providerElement(TelemetryProvider));

		expect(engagementPayloads()).toEqual([
			expect.objectContaining({
				durationDeltaMs: 1000,
				durationMs: 1000,
				path: "/jobs",
				reason: "route_change",
				sequence: 1,
				visibleDurationDeltaMs: 1000,
				visibleDurationMs: 1000,
			}),
		]);
		expect(telemetryMock.trackTelemetry).toHaveBeenCalledWith("page_view", {
			path: "/docs",
			title: "OpenOpps",
		});
	});

	it("does not double-count a hidden page when the provider unmounts", async () => {
		const { TelemetryProvider } = await import("./telemetry-provider");
		const view = renderProvider(TelemetryProvider);
		telemetryMock.trackTelemetry.mockClear();

		currentNow = 510;
		setVisibilityState("hidden");
		document.dispatchEvent(new Event("visibilitychange"));
		view.unmount();

		expect(engagementPayloads()).toEqual([
			expect.objectContaining({
				durationDeltaMs: 500,
				durationMs: 500,
				path: "/jobs",
				reason: "visibility_hidden",
				sequence: 1,
				visibleDurationDeltaMs: 500,
				visibleDurationMs: 500,
			}),
		]);
		expect(telemetryMock.flushTelemetry).toHaveBeenCalledWith(
			"visibility_hidden_engagement",
		);
	});

	it("emits non-overlapping deltas across hidden, visible, and route-change events", async () => {
		const { TelemetryProvider } = await import("./telemetry-provider");
		const view = renderProvider(TelemetryProvider);
		telemetryMock.trackTelemetry.mockClear();

		currentNow = 210;
		setVisibilityState("hidden");
		document.dispatchEvent(new Event("visibilitychange"));

		currentNow = 310;
		setVisibilityState("visible");
		document.dispatchEvent(new Event("visibilitychange"));

		currentNow = 610;
		navigationMock.pathname = "/docs";
		view.rerender(providerElement(TelemetryProvider));

		expect(engagementPayloads()).toEqual([
			expect.objectContaining({
				durationDeltaMs: 200,
				durationMs: 200,
				reason: "visibility_hidden",
				sequence: 1,
				visibleDurationDeltaMs: 200,
				visibleDurationMs: 200,
			}),
			expect.objectContaining({
				durationDeltaMs: 400,
				durationMs: 600,
				reason: "route_change",
				sequence: 2,
				visibleDurationDeltaMs: 300,
				visibleDurationMs: 500,
			}),
		]);
	});

	it("starts masked PostHog replay without overriding project controls", async () => {
		vi.stubEnv("NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED", "true");
		vi.stubEnv("NEXT_PUBLIC_OPENOPPS_POSTHOG_PROJECT_API_KEY", "phc_test");
		const { TelemetryProvider } = await import("./telemetry-provider");

		renderProvider(TelemetryProvider);

		await vi.waitFor(() => expect(posthogMock.init).toHaveBeenCalledOnce());
		expect(posthogMock.startSessionRecording).toHaveBeenCalledWith();
	});
});

function renderProvider(TelemetryProvider: (props: { children: ReactNode }) => ReactNode) {
	return render(providerElement(TelemetryProvider));
}

function providerElement(
	TelemetryProvider: (props: { children: ReactNode }) => ReactNode,
) {
	return (
		<TelemetryProvider>
			<div>Telemetry child</div>
		</TelemetryProvider>
	);
}

function engagementPayloads() {
	return telemetryMock.trackTelemetry.mock.calls
		.filter(([eventName]) => eventName === "page_engagement")
		.map(([, payload]) => payload);
}

function setVisibilityState(value: DocumentVisibilityState) {
	Object.defineProperty(document, "visibilityState", {
		configurable: true,
		value,
	});
}
