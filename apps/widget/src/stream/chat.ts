/**
 * Conversation state (plan §5).
 *
 * Holds the `chat_session_id` (the conversation identifier, distinct from the
 * widget session token — plan §3.2.1), the message list, and the streaming
 * buffer. The UI subscribes via `onChange`.
 *
 * Phase 10 additions: per-message `sources` (citation list from the SSE
 * `sources` event) and `stop()` to end a turn early (Stop-generation button)
 * without treating it as a failure.
 */

export type MessageRole = 'user' | 'assistant';

export interface ChatSource {
  chunk_id?: string;
  url?: string;
  title?: string;
  score?: number;
  citation?: string;
}

/**
 * Visitor feedback state on a completed assistant turn (Phase 12.4).
 * The widget only ever sends 5 (thumbs up) or 1 (thumbs down) on the backend's
 * 1-5 scale (ADR-005 §5.6). `status` drives the control: idle → submitting →
 * submitted, or error (with a retry path).
 */
export type FeedbackStatus = 'idle' | 'submitting' | 'submitted' | 'error';

export interface FeedbackState {
  status: FeedbackStatus;
  rating: 1 | 5;
  category: string;
  comment: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  streaming?: boolean;
  error?: boolean;
  /** True when the user stopped the turn early (partial answer kept). */
  stopped?: boolean;
  /** Citation list attached to an assistant turn (Phase 10). */
  sources?: ChatSource[];
  /** Backend `message_id` from the SSE `done` event (Phase 12.4). */
  messageId?: string;
  /** Visitor feedback state (Phase 12.4). */
  feedback?: FeedbackState;
}

export interface ConversationState {
  messages: ChatMessage[];
  sessionId: string | null;
  streaming: boolean;
  error: string | null;
}

export interface ConversationOptions {
  sessionId?: string | null;
  onChange?: (state: ConversationState) => void;
}

let idCounter = 0;
function nextId(): string {
  idCounter += 1;
  return `msg-${Date.now()}-${idCounter}`;
}

export class Conversation {
  private messages: ChatMessage[] = [];
  private sessionId: string | null;
  private streaming = false;
  private error: string | null = null;
  onChange?: (state: ConversationState) => void;

  constructor(options: ConversationOptions = {}) {
    this.sessionId = options.sessionId ?? null;
    this.onChange = options.onChange;
  }

  getState(): ConversationState {
    return {
      messages: [...this.messages],
      sessionId: this.sessionId,
      streaming: this.streaming,
      error: this.error,
    };
  }

  private emit(): void {
    this.onChange?.(this.getState());
  }

  addUserMessage(content: string): void {
    this.messages.push({ id: nextId(), role: 'user', content });
    this.emit();
  }

  /** Start an assistant turn; returns the placeholder message id. */
  startAssistantTurn(): string {
    const message: ChatMessage = { id: nextId(), role: 'assistant', content: '', streaming: true };
    this.messages.push(message);
    this.streaming = true;
    this.error = null;
    this.emit();
    return message.id;
  }

  /** Append a delta to the currently streaming assistant message. */
  appendDelta(id: string, delta: string): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.content += delta;
      this.emit();
    }
  }

  /** Attach the citation/source list to an assistant turn (SSE `sources`). */
  setSources(id: string, sources: ChatSource[]): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.sources = sources;
      this.emit();
    }
  }

  /** Bind the backend `message_id` to an assistant turn (SSE `done`). */
  setMessageId(id: string, messageId: string): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.messageId = messageId;
      this.emit();
    }
  }

  /** Record the feedback state of an assistant turn (Phase 12.4). */
  setFeedback(id: string, feedback: FeedbackState): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.feedback = feedback;
      this.emit();
    }
  }

  /** End an assistant turn cleanly. */
  endTurn(id: string): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.streaming = false;
    }
    this.streaming = false;
    this.emit();
  }

  /**
   * Stop the current assistant turn early (Stop-generation button). The partial
   * answer is kept and marked `stopped`; this is not an error.
   */
  stopTurn(id: string): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.streaming = false;
      message.stopped = true;
    }
    this.streaming = false;
    this.emit();
  }

  /** Record a failed assistant turn (keeps the bubble, marks it failed). */
  failTurn(id: string, error: string | null = null): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.streaming = false;
      message.error = true;
    }
    this.streaming = false;
    this.error = error;
    this.emit();
  }

  setSessionId(sessionId: string): void {
    this.sessionId = sessionId;
    this.emit();
  }

  clear(): void {
    this.messages = [];
    this.sessionId = null;
    this.streaming = false;
    this.error = null;
    this.emit();
  }
}
