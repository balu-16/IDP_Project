import { useDropzone } from 'react-dropzone';
import { Upload } from 'lucide-react';
import { showToast } from '@/components/Toast';
import { cn } from '@/lib/utils';

export interface FileItem { id: string; file: File; type: 'pdf' | 'image'; }
export default function FileDropzone({ onFilesChange, className }: {
  onFilesChange: (files: FileItem[]) => void; className?: string;
}) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'], 'image/png': ['.png'], 'image/jpeg': ['.jpg', '.jpeg'] },
    maxSize: 10 * 1024 * 1024, maxFiles: 5,
    onDropAccepted: files => onFilesChange(files.map(file => ({
      id: crypto.randomUUID(), file, type: file.type.startsWith('image/') ? 'image' : 'pdf',
    }))),
    onDropRejected: files => showToast('error', 'File rejected',
      files.map(item => item.file.name + ': ' + item.errors.map(e => e.message).join(', ')).join('\n')),
  });
  return <div {...getRootProps()} className={cn('cursor-pointer rounded-lg border-2 border-dashed border-border p-8 text-center', className)}>
    <input {...getInputProps()} aria-label="Select documents" />
    <Upload className="mx-auto mb-3 text-primary" />
    <p>{isDragActive ? 'Drop documents here' : 'Drop files here or click to select'}</p>
    <p className="mt-2 text-xs text-text-secondary">Up to five PDFs or images per upload.</p>
  </div>;
}
