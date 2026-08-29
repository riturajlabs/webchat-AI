import { describe, expect, it } from 'vitest';

import {
  buildEmbedScript,
  buildInitExample,
  buildMountExample,
  DASHBOARD_URL,
  describeEmbedEnvironment,
  DOCS_WIDGET_ID,
  WIDGET_API_URL,
  WIDGET_SCRIPT_URL,
} from './embed';

describe('buildEmbedScript', () => {
  it('includes the widget id and the configured script src', () => {
    expect(buildEmbedScript('widget_abc123')).toBe(
      `<script src="${WIDGET_SCRIPT_URL}" ` + 'data-widget-id="widget_abc123" defer></script>',
    );
  });

  it('escapes nothing and never references localhost or placeholder hosts', () => {
    const script = buildEmbedScript(DOCS_WIDGET_ID);
    expect(script).toContain(`data-widget-id="${DOCS_WIDGET_ID}"`);
    expect(script.toLowerCase()).not.toContain('localhost');
    expect(script.toLowerCase()).not.toContain('127.0.0.1');
    expect(script.toLowerCase()).not.toContain('.example');
  });

  it('honors a custom script src', () => {
    expect(buildEmbedScript('widget_1', 'https://cdn.custom.example/widget.js')).toContain(
      'src="https://cdn.custom.example/widget.js"',
    );
  });
});

describe('buildInitExample', () => {
  it('embeds the widget id and omits the api base by default', () => {
    const code = buildInitExample('widget_abc123');
    expect(code).toContain("widgetId: 'widget_abc123'");
    expect(code).not.toContain('apiBaseUrl');
  });

  it('includes the production api base when requested', () => {
    const code = buildInitExample('widget_abc123', WIDGET_API_URL);
    expect(code).toContain(`apiBaseUrl: '${WIDGET_API_URL}'`);
    expect(code).not.toContain('localhost');
    expect(code).not.toContain('.example');
  });
});

describe('buildMountExample', () => {
  it('embeds the widget id and the host option', () => {
    const code = buildMountExample('widget_abc123');
    expect(code).toContain("widgetId: 'widget_abc123'");
    expect(code).toContain("host: document.querySelector('#my-chat')");
  });

  it('never references localhost', () => {
    expect(buildMountExample(DOCS_WIDGET_ID).toLowerCase()).not.toContain('localhost');
  });
});

describe('embedded URL constants', () => {
  it('always resolves production-style, real hosts (never placeholders)', () => {
    for (const url of [WIDGET_SCRIPT_URL, WIDGET_API_URL, DASHBOARD_URL]) {
      expect(url).toMatch(/^https:\/\//);
      expect(url.toLowerCase()).not.toContain('localhost');
      expect(url.toLowerCase()).not.toContain('127.0.0.1');
      expect(url.toLowerCase()).not.toContain('.example');
    }
  });
});

describe('describeEmbedEnvironment', () => {
  it('flags a localhost snippet as development', () => {
    const env = describeEmbedEnvironment(
      '<script src="http://localhost:8080/webchat-widget.iife.min.js" ' +
        'data-widget-id="w-1" data-api-base-url="http://localhost:8000" defer></script>',
    );
    expect(env.kind).toBe('development');
    expect(env.title).toBe('Development snippet');
    expect(env.message.toLowerCase()).toContain('localhost');
  });

  it('flags a CDN snippet as production', () => {
    const env = describeEmbedEnvironment(buildEmbedScript('widget_abc123'));
    expect(env.kind).toBe('production');
    expect(env.title).toBe('Production snippet');
    expect(env.message.toLowerCase()).not.toContain('localhost');
  });
});
