import type { MetadataRoute } from 'next';

import { SITE_URL } from '@/lib/site';

const PRIVATE_PATHS = [
  '/dashboard',
  '/admin',
  '/websites',
  '/knowledge',
  '/conversations',
  '/analytics',
  '/usage',
  '/billing',
  '/widget',
  '/widget-test',
  '/api-keys',
  '/profile',
  '/settings',
  '/verify-email',
  '/reset-password',
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: PRIVATE_PATHS,
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
