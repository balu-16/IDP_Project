import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, X, FileText, Image } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';

interface FileItem {
  id: string;
  file: File;
  type: 'pdf' | 'image';
}

interface FileDropzoneProps {
  onFilesChange: (files: FileItem[]) => void;
  className?: string;
}

const FileDropzone: React.FC<FileDropzoneProps> = ({ onFilesChange, className }) => {
  const [files, setFiles] = useState<FileItem[]>([]);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles: FileItem[] = acceptedFiles.map((file) => ({
      id: Math.random().toString(36).substr(2, 9),
      file,
      type: file.type.startsWith('image/') ? 'image' : 'pdf'
    }));
    
    const updatedFiles = [...files, ...newFiles];
    setFiles(updatedFiles);
    onFilesChange(updatedFiles);
  }, [files, onFilesChange]);

  const removeFile = (id: string) => {
    const updatedFiles = files.filter(f => f.id !== id);
    setFiles(updatedFiles);
    onFilesChange(updatedFiles);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'image/*': ['.png', '.jpg', '.jpeg']
    },
    multiple: true
  });

  const getFileIcon = (type: string) => {
    return type === 'pdf' ? FileText : Image;
  };

  return (
    <div className={cn('space-y-4', className)}>
      <div
        {...getRootProps()}
        className={cn(
          'glass-panel border-2 border-dashed cursor-pointer transition-all duration-200',
          'hover:border-primary/50 hover:glow-caramel',
          isDragActive && 'border-primary glow-caramel scale-105'
        )}
      >
        <input {...getInputProps()} />
        <div className="p-8 text-center">
          <motion.div
            animate={{ 
              scale: isDragActive ? 1.1 : 1,
              rotate: isDragActive ? 5 : 0 
            }}
            transition={{ duration: 0.2 }}
          >
            <Upload className="w-12 h-12 mx-auto mb-4 text-primary" />
          </motion.div>
          <h3 className="text-lg font-medium text-text-primary mb-2">
            {isDragActive ? 'Drop files here' : 'Upload Files'}
          </h3>
          <p className="text-text-secondary">
            Drag & drop PDFs and images, or click to browse
          </p>
        </div>
      </div>

      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="space-y-2"
          >
            {files.map((fileItem) => {
              const Icon = getFileIcon(fileItem.type);
              return (
                <motion.div
                  key={fileItem.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  className="glass-panel p-3 flex items-center gap-3"
                >
                  <Icon className="w-5 h-5 text-primary flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate">
                      {fileItem.file.name}
                    </div>
                    <div className="text-xs text-text-secondary">
                      {(fileItem.file.size / 1024 / 1024).toFixed(2)} MB
                    </div>
                  </div>
                  <button
                    onClick={() => removeFile(fileItem.id)}
                    className="p-1 rounded-full hover:bg-error-bg text-text-secondary hover:text-error-text transition-colors"
                  >
                    <X size={16} />
                  </button>
                </motion.div>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default FileDropzone;