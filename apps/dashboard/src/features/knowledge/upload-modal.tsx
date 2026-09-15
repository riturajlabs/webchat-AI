'use client';

import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { FileText, Loader2, UploadCloud, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { useAccessibleDialog } from '@/hooks/use-accessible-dialog';

import { useUploadDocuments } from './hooks';

const ALLOWED_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx'];
const MAX_FILES = 5;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadKnowledgeDialog({
  open,
  onOpenChange,
  websiteId,
  websiteName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  websiteId: string;
  websiteName?: string;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const uploadMutation = useUploadDocuments(websiteId);

  const close = () => {
    if (uploadMutation.isPending) return;
    onOpenChange(false);
    setSelectedFiles([]);
  };

  useAccessibleDialog({
    open,
    onClose: close,
    contentRef,
  });

  const validateAndAddFiles = (newFiles: FileList | File[]) => {
    const fileArray = Array.from(newFiles);
    const valid: File[] = [];

    let currentTotalSize = selectedFiles.reduce((acc, f) => acc + f.size, 0);

    for (const file of fileArray) {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        toast.error(`'${file.name}' is not supported. Use .txt, .md, .pdf, or .docx.`);
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        toast.error(`'${file.name}' exceeds maximum allowed file size of 10 MB.`);
        continue;
      }
      if (currentTotalSize + file.size > MAX_FILE_SIZE_BYTES) {
        toast.error('Total batch size exceeds 10 MB limit.');
        break;
      }
      if (selectedFiles.length + valid.length >= MAX_FILES) {
        toast.error(`Maximum of ${MAX_FILES} files allowed per upload.`);
        break;
      }

      // Avoid selecting the same file twice
      const isDuplicate = selectedFiles.some(
        (f) => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified,
      );
      if (!isDuplicate) {
        valid.push(file);
        currentTotalSize += file.size;
      }
    }

    if (valid.length > 0) {
      setSelectedFiles((prev) => [...prev, ...valid]);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndAddFiles(e.target.files);
    }
    // reset input so the same file can be chosen again if removed
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndAddFiles(e.dataTransfer.files);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    if (selectedFiles.length === 0 || uploadMutation.isPending) return;

    try {
      const res = await uploadMutation.mutateAsync(selectedFiles);
      toast.success(
        `${res.uploaded.length} file${res.uploaded.length === 1 ? '' : 's'} uploaded and queued for embedding.`,
      );
      onOpenChange(false);
      setSelectedFiles([]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to upload files. Please try again.');
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="upload-knowledge-title"
    >
      <div
        className="fixed inset-0 bg-background/80 backdrop-blur-sm"
        aria-hidden="true"
        onClick={close}
      />
      <div
        ref={contentRef}
        className="relative z-10 w-full max-w-lg rounded-lg border bg-card p-6 shadow-lg sm:p-8"
      >
        <button
          type="button"
          onClick={close}
          disabled={uploadMutation.isPending}
          className="absolute right-4 top-4 rounded-sm opacity-70 transition-opacity hover:opacity-100 disabled:pointer-events-none"
          aria-label="Close dialog"
        >
          <X className="size-4" />
        </button>

        <div className="space-y-1">
          <h2 id="upload-knowledge-title" className="text-lg font-semibold leading-none">
            Upload Knowledge Files
          </h2>
          <p className="text-sm text-muted-foreground">
            {websiteName
              ? `Attach documentation files to ${websiteName}.`
              : 'Attach documentation files directly to your knowledge base.'}
          </p>
        </div>

        <div className="mt-6 space-y-4">
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
              dragOver
                ? 'border-primary bg-primary/5'
                : 'border-muted-foreground/25 hover:border-primary/50'
            }`}
          >
            <UploadCloud className="size-10 text-muted-foreground" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium">Click to select or drag and drop files here</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Supported formats: .txt, .md, .pdf, .docx (Max 10 MB per file, up to 5 files)
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".txt,.md,.pdf,.docx"
              onChange={handleFileChange}
              className="hidden"
              aria-label="Upload files"
              data-autofocus
            />
          </div>

          {selectedFiles.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Selected Files ({selectedFiles.length}/{MAX_FILES})
              </p>
              <ul className="max-h-48 overflow-y-auto divide-y rounded-md border bg-muted/20 px-3">
                {selectedFiles.map((file, idx) => (
                  <li
                    key={`${file.name}-${idx}`}
                    className="flex items-center justify-between py-2 text-sm"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate font-medium">{file.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        ({formatFileSize(file.size)})
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeFile(idx);
                      }}
                      disabled={uploadMutation.isPending}
                      className="text-muted-foreground hover:text-destructive p-1"
                      aria-label={`Remove ${file.name}`}
                    >
                      <X className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={close}
              disabled={uploadMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={selectedFiles.length === 0 || uploadMutation.isPending}
              className="gap-2"
            >
              {uploadMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  <span>Uploading…</span>
                </>
              ) : (
                <span>Upload & Embed</span>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
