import { createMDX } from 'fumadocs-mdx/next';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const withMDX = createMDX();
const root = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  experimental: {
    cpus: 1,
  },
  // `pnpm types:check` is the explicit docs type gate before production builds.
  typescript: {
    ignoreBuildErrors: false,
  },
  async redirects() {
    return [
      {
        source: '/jobs',
        destination: '/',
        permanent: true,
      },
      {
        source: '/docs/explorer',
        destination: '/explorer',
        permanent: true,
      },
    ];
  },
  turbopack: {
    root,
  },
};

export default withMDX(config);
