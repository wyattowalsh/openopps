import { createMDX } from 'fumadocs-mdx/next';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const withMDX = createMDX();
const root = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  // Keep web/AGENTS.md as the OpenOpps SSOT; next dev otherwise appends a generated block.
  agentRules: false,
  experimental: {
    cpus: 1,
  },
  // Keep large committed search shards out of serverless function traces.
  outputFileTracingExcludes: {
    '*': [
      './public/data/openopps-search/**/*',
      'public/data/openopps-search/**/*',
    ],
  },
  images: {
    formats: ['image/avif', 'image/webp'],
  },
  // `pnpm types:check` is the explicit docs type gate before production builds.
  typescript: {
    ignoreBuildErrors: false,
  },
  async headers() {
    return [
      {
        source: '/data/openopps-search/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=300, stale-while-revalidate=86400',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
        ],
      },
      {
        source: '/_next/static/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
        ],
      },
    ];
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
