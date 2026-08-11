'use client';

import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const MAX_QUESTIONS = 5;
const MAX_QUESTION_LENGTH = 200;

export function QuestionEditor({
  questions,
  onChange,
}: {
  questions: string[];
  onChange: (questions: string[]) => void;
}) {
  function update(index: number, value: string) {
    const next = [...questions];
    next[index] = value;
    onChange(next);
  }

  function remove(index: number) {
    onChange(questions.filter((_, i) => i !== index));
  }

  function add() {
    if (questions.length < MAX_QUESTIONS) {
      onChange([...questions, '']);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <Label>Suggested questions</Label>
        <span className="text-xs text-muted-foreground">
          {questions.length}/{MAX_QUESTIONS}
        </span>
      </div>
      {questions.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          No suggested questions yet. Add a few to help visitors start a conversation.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {questions.map((question, index) => (
            <li key={index} className="flex items-center gap-2">
              <Input
                value={question}
                maxLength={MAX_QUESTION_LENGTH}
                aria-label={`Suggested question ${index + 1}`}
                placeholder={`Question ${index + 1}`}
                onChange={(event) => update(index, event.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove question ${index + 1}`}
                onClick={() => remove(index)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={add}
        disabled={questions.length >= MAX_QUESTIONS}
        className="self-start"
      >
        <Plus aria-hidden="true" />
        Add question
      </Button>
    </div>
  );
}
