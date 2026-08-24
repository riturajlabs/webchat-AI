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
export type { SessionManager } from './core/session';
export type {
  WidgetOptions,
  WidgetOverride,
  WidgetPublicConfig,
  WidgetPosition,
} from './config/types';
export type { ChatMessage, ChatSource, FeedbackState } from './stream/chat';

/**
 * Auto-upgrade from an embed script carrying `data-widget-id`, or mount the
 * widget when called programmatically. Returns the widget controller.
 */
export function init(options: WidgetOptions): WidgetController {
  return mount(options);
}

// Embed flow: `data-widget-id` on the script tag (or on individual hosts)
// upgrades automatically, so `<script src=... data-widget-id=abc defer>`
// works with no init() call — including multiple hosts on the same page.
for (const embedded of autoUpgrade()) {
  void embedded.controller;
}

defineWidgetElement();

export default { init };
