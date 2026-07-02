export function cleanText(value: unknown) {
	return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

export function safeJobExternalUrl(value: unknown) {
	const raw = cleanText(value);
	if (!raw) {
		return null;
	}
	try {
		const parsed = new URL(raw);
		if (parsed.username || parsed.password) {
			return null;
		}
		if (parsed.protocol === "http:" || parsed.protocol === "https:") {
			return parsed.toString();
		}
	} catch {
		return null;
	}
	return null;
}
