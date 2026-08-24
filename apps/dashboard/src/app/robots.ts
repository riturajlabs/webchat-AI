import type { MetadataRoute } from 'next';

import { SITE_URL } from '@/lib/site';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      // Authenticated surfaces: nothing indexable, keep crawlers out.
      disallow: ['/admin', '/api'],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
