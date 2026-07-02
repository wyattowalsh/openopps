export function docsOgPageSlug(slug: string[]): string[] | null {
	if (slug.at(-1) !== "image.png") {
		return null;
	}
	return slug.slice(0, -1);
}
