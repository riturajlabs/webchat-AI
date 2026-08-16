import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  transpilePackages: ['@webchat/themes'],
};

export default nextConfig;
