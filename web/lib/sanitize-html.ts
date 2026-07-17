import DOMPurify from "isomorphic-dompurify";

const ALLOWED_DESCRIPTION_TAGS = [
	"a",
	"b",
	"blockquote",
	"br",
	"code",
	"div",
	"em",
	"h2",
	"h3",
	"h4",
	"i",
	"li",
	"ol",
	"p",
	"pre",
	"span",
	"strong",
	"u",
	"ul",
];

function hardenExternalLinks(element: Element) {
	if (element.tagName !== "A") {
		return;
	}
	const href = element.getAttribute("href");
	if (!href) {
		return;
	}
	try {
		if (!href.startsWith("http://") && !href.startsWith("https://")) {
			element.removeAttribute("href");
			return;
		}
		const parsed = new URL(href);
		if (
			(parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
			parsed.username ||
			parsed.password
		) {
			element.removeAttribute("href");
			return;
		}
	} catch {
		element.removeAttribute("href");
		return;
	}
	element.setAttribute("target", "_blank");
	element.setAttribute("rel", "noopener noreferrer");
}

export function sanitizeJobDescriptionHtml(source: string) {
	if (!source.trim()) {
		return "";
	}
	DOMPurify.addHook("afterSanitizeAttributes", hardenExternalLinks);
	try {
		return DOMPurify.sanitize(source, {
			ALLOWED_TAGS: ALLOWED_DESCRIPTION_TAGS,
			ALLOWED_ATTR: ["href", "title"],
			ALLOW_DATA_ATTR: false,
			FORBID_TAGS: ["iframe", "link", "meta", "object", "script", "style", "template"],
			RETURN_TRUSTED_TYPE: false,
		});
	} finally {
		DOMPurify.removeHook("afterSanitizeAttributes");
	}
}
