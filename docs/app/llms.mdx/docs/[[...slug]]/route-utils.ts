export function docsMarkdownPageSlug(slug: string[] | undefined): string[] | null {
	if (!slug?.length || slug.at(-1) !== "content.md") {
		return null;
	}
	return slug.slice(0, -1);
}
