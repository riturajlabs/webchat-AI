import { describe, expect, it } from 'vitest';
import {
  detectIntent,
  isNoContextAnswer,
  NO_CONTEXT_ANSWER,
  NO_CONTEXT_REPLY,
  normalizeText,
} from './intent';

describe('detectIntent', () => {
  it('classifies plain greetings', () => {
    for (const phrase of ['hi', 'hello', 'hey', 'howdy', 'good morning', 'good evening']) {
      const match = detectIntent(phrase);
      expect(match?.intent).toBe('greeting');
      expect(match?.reply).toContain('How can I help you today?');
    }
  });

  it('classifies greetings regardless of case and trailing punctuation', () => {
    expect(detectIntent('Hello!')?.intent).toBe('greeting');
    expect(detectIntent('HELLO')?.intent).toBe('greeting');
    expect(detectIntent('  hi  ')?.intent).toBe('greeting');
    expect(detectIntent('Good morning!!')?.intent).toBe('greeting');
    expect(detectIntent('hi there')?.intent).toBe('greeting');
    expect(detectIntent('hey 👋')?.intent).toBe('greeting');
  });

  it('classifies thanks phrases with the polite reply', () => {
    for (const phrase of ['thanks', 'thank you', 'thank you so much', 'thx', 'ty']) {
      const match = detectIntent(phrase);
      expect(match?.intent).toBe('thanks');
      expect(match?.reply).toContain("You're welcome!");
    }
    expect(detectIntent('Thanks!')?.intent).toBe('thanks');
  });

  it('classifies farewells', () => {
    for (const phrase of ['bye', 'goodbye', 'see you later']) {
      expect(detectIntent(phrase)?.intent).toBe('farewell');
    }
  });

  it('returns null for real questions so RAG handles them', () => {
    for (const question of [
      'what is pricing',
      'hello, what are your prices?',
      'how do I reset my password',
      'hi, can you help me with refunds',
      'thanks, how do I cancel my plan',
      'courses offered',
      'tell me about admission',
      '12345',
    ]) {
      expect(detectIntent(question)).toBeNull();
    }
  });

  it('returns null for empty / non-word input', () => {
    expect(detectIntent('')).toBeNull();
    expect(detectIntent('   ')).toBeNull();
    expect(detectIntent('!!!')).toBeNull();
  });
});

describe('normalizeText', () => {
  it('lowercases, strips punctuation and collapses whitespace', () => {
    expect(normalizeText('  Hello,  World!!  ')).toBe('hello world');
    expect(normalizeText('café ☕')).toBe('café');
  });
});

describe('isNoContextAnswer', () => {
  it('matches the backend fallback verbatim and lightly varied', () => {
    expect(isNoContextAnswer(NO_CONTEXT_ANSWER)).toBe(true);
    expect(isNoContextAnswer(NO_CONTEXT_ANSWER + '  ')).toBe(true);
    expect(
      isNoContextAnswer("I couldn't find that information in the website's knowledge base!"),
    ).toBe(true);
    expect(isNoContextAnswer('I know the answer')).toBe(false);
  });

  it('defines the friendly rewrite', () => {
    expect(NO_CONTEXT_REPLY).toContain('Could you try asking another question?');
  });
});
