import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UploadKnowledgeDialog } from './upload-modal';
import { useUploadDocuments } from './hooks';

vi.mock('./hooks', () => ({
  useUploadDocuments: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const mockedUseUploadDocuments = vi.mocked(useUploadDocuments);

describe('UploadKnowledgeDialog', () => {
  const onOpenChange = vi.fn();
  const mutateAsync = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mutateAsync.mockResolvedValue({
      website_id: 'site-1',
      uploaded: [
        {
          id: 'doc-1',
          website_id: 'site-1',
          file_name: 'test.pdf',
          file_size_bytes: 1024,
          mime_type: 'application/pdf',
          status: 'pending',
          char_count: 500,
        },
      ],
    });
    mockedUseUploadDocuments.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useUploadDocuments>);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders modal when open is true', () => {
    render(
      <UploadKnowledgeDialog
        open={true}
        onOpenChange={onOpenChange}
        websiteId="site-1"
        websiteName="Acme Inc"
      />,
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Upload Knowledge Files')).toBeInTheDocument();
    expect(screen.getByText(/drag and drop files here/i)).toBeInTheDocument();
    expect(screen.getByText(/.txt, .md, .pdf, .docx/i)).toBeInTheDocument();
  });

  it('does not render when open is false', () => {
    render(
      <UploadKnowledgeDialog
        open={false}
        onOpenChange={onOpenChange}
        websiteId="site-1"
        websiteName="Acme Inc"
      />,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('accepts valid files via file input', () => {
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const file = new File(['hello world knowledge content'], 'guide.txt', { type: 'text/plain' });
    const input = screen.getByLabelText(/Upload files/i);

    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('guide.txt')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Upload & Embed/i })).toBeInTheDocument();
  });

  it('rejects unsupported file formats with toast error', async () => {
    const { toast } = await import('sonner');
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const invalidFile = new File(['content'], 'malware.exe', { type: 'application/x-msdownload' });
    const input = screen.getByLabelText(/Upload files/i);

    fireEvent.change(input, { target: { files: [invalidFile] } });

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('is not supported'));
    expect(screen.queryByText('malware.exe')).not.toBeInTheDocument();
  });

  it('rejects files larger than 10 MB', async () => {
    const { toast } = await import('sonner');
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    // 11 MB file
    const largeFile = new File(['x'.repeat(100)], 'large.pdf', { type: 'application/pdf' });
    Object.defineProperty(largeFile, 'size', { value: 11 * 1024 * 1024 });

    const input = screen.getByLabelText(/Upload files/i);
    fireEvent.change(input, { target: { files: [largeFile] } });

    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining('exceeds maximum allowed file size of 10 MB'),
    );
    expect(screen.queryByText('large.pdf')).not.toBeInTheDocument();
  });

  it('rejects adding more than 5 files', async () => {
    const { toast } = await import('sonner');
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const files = [1, 2, 3, 4, 5, 6].map(
      (n) => new File([`content ${n}`], `doc${n}.txt`, { type: 'text/plain' }),
    );

    const input = screen.getByLabelText(/Upload files/i);
    fireEvent.change(input, { target: { files } });

    expect(toast.error).toHaveBeenCalledWith('Maximum of 5 files allowed per upload.');
  });

  it('allows removing a selected file before uploading', () => {
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const file = new File(['content'], 'doc.pdf', { type: 'application/pdf' });
    const input = screen.getByLabelText(/Upload files/i);
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('doc.pdf')).toBeInTheDocument();
    const removeBtn = screen.getByRole('button', { name: /Remove doc.pdf/i });
    fireEvent.click(removeBtn);

    expect(screen.queryByText('doc.pdf')).not.toBeInTheDocument();
  });

  it('submits selected files and triggers success toast', async () => {
    const { toast } = await import('sonner');
    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const file = new File(['content'], 'doc.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    const input = screen.getByLabelText(/Upload files/i);
    fireEvent.change(input, { target: { files: [file] } });

    const uploadBtn = screen.getByRole('button', { name: /Upload & Embed/i });
    fireEvent.click(uploadBtn);

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith('1 file uploaded and queued for embedding.');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('handles upload failure with error toast', async () => {
    const { toast } = await import('sonner');
    mutateAsync.mockRejectedValueOnce(new Error('Network error during upload'));

    render(<UploadKnowledgeDialog open={true} onOpenChange={onOpenChange} websiteId="site-1" />);

    const file = new File(['content'], 'doc.txt', { type: 'text/plain' });
    const input = screen.getByLabelText(/Upload files/i);
    fireEvent.change(input, { target: { files: [file] } });

    const uploadBtn = screen.getByRole('button', { name: /Upload & Embed/i });
    fireEvent.click(uploadBtn);

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(toast.error).toHaveBeenCalledWith('Network error during upload');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
