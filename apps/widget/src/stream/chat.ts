/**
 * Conversation state (plan §5).
 *
 * Holds the `chat_session_id` (the conversation identifier, distinct from the
 * widget session token — plan §3.2.1), the message list, and the streaming
 * buffer. The UI subscribes via `onChange`.
 */

export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  streaming?: boolean;
  error?: boolean;
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

  /** End an assistant turn cleanly. */
  endTurn(id: string): void {
    const message = this.messages.find((m) => m.id === id);
    if (message) {
      message.streaming = false;
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
