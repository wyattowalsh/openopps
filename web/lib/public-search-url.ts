/**
 * Resolve public search-artifact paths against an allowlisted base origin.
 * Rejects absolute / scheme-relative / traversal paths that would leave the base origin.
 */
export function resolvePublicSearchUrl(base: URL, publicPath: string): URL {
	const path = publicPath.trim();
	if (!path) {
		throw new Error("public search path is empty");
	}
	if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(path)) {
		throw new Error("public search path must be relative (no scheme)");
	}
	if (path.startsWith("//")) {
		throw new Error("public search path must not be scheme-relative");
	}
	if (path.includes("\\")) {
		throw new Error("public search path must not contain backslashes");
	}
	const segments = path.split("/").filter((segment) => segment.length > 0);
	if (segments.some((segment) => segment === "." || segment === "..")) {
		throw new Error("public search path must not contain '.' or '..' segments");
	}
	const resolved = new URL(path, base);
	if (resolved.origin !== base.origin) {
		throw new Error("public search path must stay on the allowlisted origin");
	}
	const prefix = "/data/openopps-search";
	const pathname = resolved.pathname;
	if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) {
		throw new Error(`public search path must be under ${prefix}/`);
	}
	return resolved;
}
