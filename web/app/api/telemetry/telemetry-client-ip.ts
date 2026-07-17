import { isIP } from "node:net";

export type TelemetryTrustedProxyMode =
	| "none"
	| "cloudflare"
	| "vercel"
	| "forwarded";

export function normalizeTelemetryTrustedProxyMode(
	value: string | undefined,
): TelemetryTrustedProxyMode {
	if (
		value === "cloudflare" ||
		value === "vercel" ||
		value === "forwarded"
	) {
		return value;
	}
	return "none";
}

export function extractTelemetryClientIp(
	request: Request,
	mode: TelemetryTrustedProxyMode,
) {
	switch (mode) {
		case "cloudflare":
			return validIpFromHeader(request.headers.get("cf-connecting-ip"));
		case "vercel":
			return firstValidIpFromHeader(request.headers.get("x-vercel-forwarded-for"));
		case "forwarded":
			return firstValidIpFromHeader(request.headers.get("x-forwarded-for"));
		case "none":
			return undefined;
	}
}

function firstValidIpFromHeader(value: string | null) {
	return validIpFromHeader(value?.split(",")[0] ?? null);
}

function validIpFromHeader(value: string | null) {
	const candidate = value?.trim();
	if (!candidate || isIP(candidate) === 0) {
		return undefined;
	}
	return candidate;
}
