import { source } from '@/lib/source';
import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import type { Metadata } from 'next';
import { baseOptions } from '@/lib/layout.shared';
import { docsIndexMetadata } from '@/lib/site-metadata';

export const metadata: Metadata = docsIndexMetadata();

export default function Layout({ children }: LayoutProps<'/docs'>) {
  return (
    <DocsLayout tree={source.getPageTree()} {...baseOptions()}>
      <NuqsAdapter>{children}</NuqsAdapter>
    </DocsLayout>
  );
}
