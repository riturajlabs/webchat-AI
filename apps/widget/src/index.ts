/**
 * WebChat AI Widget SDK
 *
 * Framework-independent embeddable chatbot widget.
 * Entry point for the ES + UMD builds (window.WebChatWidget).
 */
import { autoUpgrade } from './core/embed';
import { mount, defineWidgetElement, type WidgetController } from './core/mount';
import type { WidgetOptions } from './config/types';

export { mount } from './core/mount';
export { autoUpgrade } from './core/embed';
export type { WidgetController } from './core/mount';
export type { WidgetOptions } from './config/types';

/**
 * Auto-upgrade from an embed script carrying `data-widget-id`, or mount the
 * widget when called programmatically. Returns the widget controller.
 */
export function init(options: WidgetOptions): WidgetController {
  return mount(options);
}

// Embed flow: `data-widget-id` on the script tag upgrades automatically, so
// `<script src=... data-widget-id=abc defer>` works with no init() call.
const embedded = autoUpgrade();
if (embedded) {
  void embedded.controller;
}

defineWidgetElement();

export default { init };
