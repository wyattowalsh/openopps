import { getLLMText, getPageMarkdownUrl, source } from '@/lib/source';
import { describedbyLlmsUrl, canonicalSiteUrl } from '@/lib/site-metadata';
import { notFound } from 'next/navigation';
import { docsMarkdownPageSlug } from './route-utils';

export const revalidate = false;

export async function GET(_req: Request, { params }: RouteContext<'/llms.mdx/docs/[[...slug]]'>) {
  const { slug } = await params;
  const pageSlug = docsMarkdownPageSlug(slug);
  if (!pageSlug) notFound();
  const page = source.getPage(pageSlug);
  if (!page) notFound();
  const htmlUrl = canonicalSiteUrl(page.url);
  const markdownUrl = canonicalSiteUrl(getPageMarkdownUrl(page).url);

  return new Response(await getLLMText(page), {
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      Link: `<${markdownUrl}>; rel="alternate"; type="text/markdown", <${htmlUrl}>; rel="canonical", <${describedbyLlmsUrl()}>; rel="describedby"`,
    },
  });
}

export function generateStaticParams() {
  return source.getPages().map((page) => ({
    lang: page.locale,
    slug: getPageMarkdownUrl(page).segments,
  }));
}
