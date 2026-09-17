# Documentation Portal Assets

## Source of Truth

The primary source of truth for WebChat AI screenshots and product demonstration media is the root `/assets` directory (`/assets/screenshots` and `/assets/demo`).

## Purpose

This directory (`apps/dashboard/public/docs-assets/`) provides concrete, cross-platform static file serving for the Next.js documentation portal (`/docs`).

Files are placed directly here rather than using a symbolic link (`apps/dashboard/public/docs-assets -> ../../../assets`) to provide a portable asset layout that does not depend on Git symlink support or Windows Developer Mode. Specifically:

1. **Cross-platform portability:** Git checkouts on Windows without symlink privileges or Developer Mode enabled do not result in broken text-pointer symlink files.
2. **Container and standalone compatibility:** Next.js standalone server deployments and Docker runner containers serve static assets directly from the dashboard application's `public/` directory without requiring references to the parent repository tree.
3. **CI/CD reliability:** Automated preview and build runners across any operating system can immediately serve documentation screenshots and demonstration video without prerequisite symlink linking scripts.

When updating product screenshots or walkthrough recordings in `/assets`, synchronize the updated files into `apps/dashboard/public/docs-assets/`.
