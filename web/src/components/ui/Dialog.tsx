import { X } from 'lucide-react';
import { Dialog as R } from 'radix-ui';
import type { ReactNode } from 'react';
import { Button } from './Button';
import s from './Dialog.module.css';

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  closeLabel: string;
  children: ReactNode;
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  closeLabel,
  children,
}: DialogProps) {
  return (
    <R.Root open={open} onOpenChange={onOpenChange}>
      <R.Portal>
        <R.Overlay className={s.overlay} />
        <R.Content
          className={s.content}
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <div className={s.header}>
            <R.Title className={s.title}>{title}</R.Title>
            <R.Close asChild>
              <Button variant="ghost" aria-label={closeLabel} style={{ width: 32, padding: 0 }}>
                <X strokeWidth={1.5} />
              </Button>
            </R.Close>
          </div>
          {description ? <R.Description className="sr-only">{description}</R.Description> : null}
          <div className={s.body}>{children}</div>
        </R.Content>
      </R.Portal>
    </R.Root>
  );
}
