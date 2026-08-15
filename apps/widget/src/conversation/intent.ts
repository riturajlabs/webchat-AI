/**
 * Lightweight conversation classifier.
 *
 * Runs BEFORE RAG retrieval so simple pleasantries (greetings, thanks,
 * farewells) get an immediate, friendly reply without ever calling the chat
 * API. Only when no intent matches is the question forwarded to the RAG
 * backend. Matching is deliberately conservative (exact phrase match after
 * normalization) so a real question that merely *starts* with a greeting word
 * ("hello, what is pricing?") still reaches the knowledge base.
 */

export type ConversationIntent = 'greeting' | 'thanks' | 'farewell';

export interface IntentMatch {
  intent: ConversationIntent;
  reply: string;
}

/**
 * The RAG backend's zero-context fallback answer
 * (`backend/prompts/rag.py` → `UNKNOWN_ANSWER_FALLBACK`), streamed verbatim
 * when retrieval yields nothing. The widget rewrites it into a friendlier
 * prompt (see `NO_CONTEXT_REPLY`).
 */
export const NO_CONTEXT_ANSWER =
  "I couldn't find that information in the website's knowledge base.";

/** Friendlier rewrite of the backend's no-context fallback. */
export const NO_CONTEXT_REPLY =
  "I couldn't find this information on this website. Could you try asking another question?";

/** Lowercase + punctuation-free normalization so variants classify identically. */
export function normalizeText(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Whether an assistant answer is the backend's zero-context fallback. */
export function isNoContextAnswer(content: string): boolean {
  return normalizeText(content) === normalizeText(NO_CONTEXT_ANSWER);
}

const REPLIES: Record<ConversationIntent, string> = {
  greeting: 'Hello 👋\n\nHow can I help you today?',
  thanks: "You're welcome! 😊\n\nLet me know if you need anything else.",
  farewell: 'Goodbye! 👋\n\nCome back anytime if you need help.',
};

/** Normalized phrase → intent. Exact matches only (see header note). */
const PHRASES: Record<string, ConversationIntent> = {
  hi: 'greeting',
  hello: 'greeting',
  hey: 'greeting',
  howdy: 'greeting',
  'hi there': 'greeting',
  'hello there': 'greeting',
  'hey there': 'greeting',
  'good morning': 'greeting',
  'good afternoon': 'greeting',
  'good evening': 'greeting',
  thanks: 'thanks',
  thank: 'thanks',
  'thank you': 'thanks',
  'thanks a lot': 'thanks',
  'thanks so much': 'thanks',
  'thank you so much': 'thanks',
  thx: 'thanks',
  ty: 'thanks',
  bye: 'farewell',
  goodbye: 'farewell',
  'bye bye': 'farewell',
  'see you': 'farewell',
  'see you later': 'farewell',
  'see ya': 'farewell',
};

/**
 * Classify a user message into a conversational intent, or `null` when it is a
 * real question that must go through RAG retrieval.
 */
export function detectIntent(raw: string): IntentMatch | null {
  const normalized = normalizeText(raw);
  if (!normalized) {
    return null;
  }
  const intent = PHRASES[normalized];
  if (!intent) {
    return null;
  }
  return { intent, reply: REPLIES[intent] };
}
