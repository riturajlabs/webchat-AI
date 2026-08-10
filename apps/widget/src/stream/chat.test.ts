import { describe, expect, it } from 'vitest';
import { Conversation } from './chat';

describe('Conversation', () => {
  it('tracks user and assistant turns with deltas', () => {
    const conversation = new Conversation();
    conversation.addUserMessage('hello');
    const id = conversation.startAssistantTurn();
    conversation.appendDelta(id, 'Hel');
    conversation.appendDelta(id, 'lo');
    conversation.endTurn(id);

    const state = conversation.getState();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({ role: 'user', content: 'hello' });
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Hello',
      streaming: false,
    });
    expect(state.streaming).toBe(false);
  });

  it('records the session id from the done event', () => {
    const conversation = new Conversation();
    conversation.setSessionId('session-1');
    expect(conversation.getState().sessionId).toBe('session-1');
  });

  it('marks failed turns with an error state', () => {
    const conversation = new Conversation();
    const id = conversation.startAssistantTurn();
    conversation.failTurn(id, 'network down');
    const state = conversation.getState();
    expect(state.messages[0].error).toBe(true);
    expect(state.messages[0].streaming).toBe(false);
    expect(state.error).toBe('network down');
  });

  it('attaches the source/citation list to an assistant turn', () => {
    const conversation = new Conversation();
    conversation.addUserMessage('q');
    const id = conversation.startAssistantTurn();
    conversation.setSources(id, [{ url: 'https://a.b', title: 'A' }]);
    const state = conversation.getState();
    expect(state.messages[1].sources).toEqual([{ url: 'https://a.b', title: 'A' }]);
    expect(state.messages[1].content).toBe('');
  });

  it('stopTurn keeps the partial answer and marks it stopped, not failed', () => {
    const conversation = new Conversation();
    conversation.addUserMessage('q');
    const id = conversation.startAssistantTurn();
    conversation.appendDelta(id, 'partial');
    conversation.stopTurn(id);
    const state = conversation.getState();
    expect(state.messages[1]).toMatchObject({
      content: 'partial',
      streaming: false,
      stopped: true,
    });
    expect(state.messages[1].error).toBeUndefined();
    expect(state.streaming).toBe(false);
    expect(state.error).toBeNull();
  });

  it('notifies subscribers on change', () => {
    const onChange = (): void => undefined;
    const spy = new (class {
      onChange = onChange;
    })();
    const conversation = new Conversation({ onChange: spy.onChange });
    let calls = 0;
    conversation.onChange = () => {
      calls += 1;
    };
    conversation.addUserMessage('x');
    expect(calls).toBeGreaterThan(0);
  });

  it('clear resets everything', () => {
    const conversation = new Conversation();
    conversation.addUserMessage('x');
    conversation.clear();
    expect(conversation.getState()).toMatchObject({
      messages: [],
      sessionId: null,
      streaming: false,
    });
  });
});
