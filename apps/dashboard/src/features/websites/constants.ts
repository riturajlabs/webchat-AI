/**
 * Single source of truth for the website-card placeholder image.
 *
 * Rendered whenever a crawled website has no usable preview image (no
 * Open Graph/Twitter metadata, no representative <img>, or the selected image
 * fails to load in the browser). Served from the dashboard's `public/`
 * directory so it needs no Next.js image-domain configuration.
 */
export const DEFAULT_WEBSITE_IMAGE = '/default-website.svg';
