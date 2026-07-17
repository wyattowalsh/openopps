import { source } from '@/lib/source';
import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import { baseOptions } from '@/lib/layout.shared';

export default function Layout({ children }: LayoutProps<'/docs'>) {
  return (
    <DocsLayout tree={source.getPageTree()} {...baseOptions()}>
      <NuqsAdapter>{children}</NuqsAdapter>
    </DocsLayout>
  );
}
