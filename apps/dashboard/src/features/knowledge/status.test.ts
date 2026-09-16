import { describe, expect, it } from 'vitest';

import { isKnowledgeDocumentTerminal } from './types';
import {
  KNOWLEDGE_POLL_INTERVAL_MS,
  deriveKnowledgeReadiness,
  isKnowledgePipelineActive,
  knowledgePollIntervalMs,
} from './status';
import type { KnowledgeDocumentSummary } from './types';
import { isChatReady, isEmbeddingInProgress } from '@/features/websites/types';
import type { Website } from '@/features/websites/types';

const SITE: Pick<Website, 'id' | 'status' | 'knowledge_status'> = {
  id: 'site-1',
  status: 'ready',
  knowledge_status: 'ready',
};

const summary = (overrides: Partial<KnowledgeDocumentSummary>): KnowledgeDocumentSummary => ({
  total: 0,
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  rate_limited: 0,
  ...overrides,
});

describe('isKnowledgePipelineActive', () => {
  it('is false for null/undefined summaries', () => {
    expect(isKnowledgePipelineActive(null)).toBe(false);
    expect(isKnowledgePipelineActive(undefined)).toBe(false);
  });

  it('is false when every document is terminal', () => {
    expect(isKnowledgePipelineActive(summary({ total: 43, completed: 43 }))).toBe(false);
    expect(isKnowledgePipelineActive(summary({ total: 43, completed: 35, failed: 8 }))).toBe(false);
  });

  it('is true while documents are pending', () => {
    expect(isKnowledgePipelineActive(summary({ total: 43, pending: 7 }))).toBe(true);
  });

  it('is true while documents are processing', () => {
    expect(isKnowledgePipelineActive(summary({ total: 43, processing: 1 }))).toBe(true);
  });

  it('is true while documents are rate_limited awaiting a deferred retry', () => {
    expect(isKnowledgePipelineActive(summary({ total: 43, rate_limited: 8 }))).toBe(true);
  });
});

describe('knowledgePollIntervalMs', () => {
  it('returns the poll interval while active', () => {
    expect(knowledgePollIntervalMs(summary({ pending: 1 }))).toBe(KNOWLEDGE_POLL_INTERVAL_MS);
    expect(knowledgePollIntervalMs(summary({ processing: 1 }))).toBe(KNOWLEDGE_POLL_INTERVAL_MS);
    expect(knowledgePollIntervalMs(summary({ rate_limited: 1 }))).toBe(KNOWLEDGE_POLL_INTERVAL_MS);
  });

  it('stops polling once the pipeline is terminal', () => {
    expect(knowledgePollIntervalMs(summary({ total: 43, completed: 43 }))).toBe(false);
    expect(knowledgePollIntervalMs(summary({ total: 43, completed: 35, failed: 8 }))).toBe(false);
    expect(knowledgePollIntervalMs(null)).toBe(false);
  });
});

describe('deriveKnowledgeReadiness', () => {
  it('never claims ready when the documents have not been observed yet', () => {
    const readiness = deriveKnowledgeReadiness(null, SITE);
    expect(readiness.known).toBe(false);
    expect(readiness.isReady).toBe(false);
    expect(readiness.isEmbedding).toBe(false);
    expect(readiness.status).toBe('ready');
  });

  it('reports embedding when the persisted status is processing but no data yet', () => {
    const readiness = deriveKnowledgeReadiness(null, {
      ...SITE,
      knowledge_status: 'processing',
    });
    expect(readiness.isEmbedding).toBe(true);
    expect(readiness.isReady).toBe(false);
  });

  it('is NOT ready while any document is processing even if website.knowledge_status is ready', () => {
    const readiness = deriveKnowledgeReadiness(
      summary({ total: 43, completed: 35, processing: 1, pending: 7 }),
      SITE,
    );
    expect(readiness.known).toBe(true);
    expect(readiness.isEmbedding).toBe(true);
    expect(readiness.isReady).toBe(false);
    expect(readiness.status).toBe('processing');
  });

  it('is NOT ready while documents are rate_limited even if website.knowledge_status is ready', () => {
    const readiness = deriveKnowledgeReadiness(
      summary({ total: 43, completed: 35, rate_limited: 8 }),
      SITE,
    );
    expect(readiness.isEmbedding).toBe(true);
    expect(readiness.isReady).toBe(false);
  });

  it('is ready only when all documents are terminal and the crawl is done', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 43, completed: 43 }), SITE);
    expect(readiness.isReady).toBe(true);
    expect(readiness.isEmbedding).toBe(false);
    expect(readiness.isSettled).toBe(true);
    expect(readiness.status).toBe('ready');
  });

  it('is not ready when the crawl itself has not finished', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 43, completed: 43 }), {
      ...SITE,
      status: 'processing',
    });
    expect(readiness.isReady).toBe(false);
  });

  it('is failed when every document drained to failed', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 43, failed: 43 }), SITE);
    expect(readiness.isFailed).toBe(true);
    expect(readiness.isReady).toBe(false);
  });

  it('stays ready when documents drained with some permanent failures', () => {
    const readiness = deriveKnowledgeReadiness(
      summary({ total: 43, completed: 41, failed: 2 }),
      SITE,
    );
    expect(readiness.isSettled).toBe(true);
    expect(readiness.isReady).toBe(true);
  });

  it('is ready for files source_mode when documents completed even if website.status is pending', () => {
    const fileSite = {
      ...SITE,
      status: 'pending' as const,
      source_mode: 'files' as const,
    };
    const readiness = deriveKnowledgeReadiness(summary({ total: 5, completed: 5 }), fileSite);
    expect(readiness.isReady).toBe(true);
    expect(readiness.isEmbedding).toBe(false);
    expect(readiness.isSettled).toBe(true);
    expect(readiness.status).toBe('ready');
  });

  it('is not ready for files source_mode if website.status is failed', () => {
    const fileSite = {
      ...SITE,
      status: 'failed' as const,
      source_mode: 'files' as const,
    };
    const readiness = deriveKnowledgeReadiness(summary({ total: 5, completed: 5 }), fileSite);
    expect(readiness.isReady).toBe(false);
  });
});

describe('isChatReady and isEmbeddingInProgress', () => {
  it('handles standard website mode', () => {
    expect(isChatReady({ status: 'ready', knowledge_status: 'ready' })).toBe(true);
    expect(isChatReady({ status: 'pending', knowledge_status: 'ready' })).toBe(false);
    expect(isEmbeddingInProgress({ status: 'ready', knowledge_status: 'processing' })).toBe(true);
  });

  it('handles files mode without requiring website status ready', () => {
    expect(
      isChatReady({
        status: 'pending',
        knowledge_status: 'ready',
        source_mode: 'files',
        knowledge_chunks: 5,
      }),
    ).toBe(true);

    expect(
      isChatReady({
        status: 'pending',
        knowledge_status: 'ready',
        source_mode: 'files',
        knowledge_chunks: 0,
      }),
    ).toBe(false);

    expect(
      isChatReady({
        status: 'failed',
        knowledge_status: 'ready',
        source_mode: 'files',
        knowledge_chunks: 5,
      }),
    ).toBe(false);

    expect(
      isEmbeddingInProgress({
        status: 'pending',
        knowledge_status: 'processing',
        source_mode: 'files',
      }),
    ).toBe(true);
  });
});

describe('isKnowledgeDocumentTerminal', () => {
  it('treats completed and failed as terminal', () => {
    expect(isKnowledgeDocumentTerminal('completed')).toBe(true);
    expect(isKnowledgeDocumentTerminal('failed')).toBe(true);
  });

  it.each(['pending', 'processing', 'rate_limited'] as const)(
    'treats %s as non-terminal',
    (status) => {
      expect(isKnowledgeDocumentTerminal(status)).toBe(false);
    },
  );
});
