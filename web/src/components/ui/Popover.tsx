import { Popover as R } from 'radix-ui';
import type { CSSProperties, ReactNode } from 'react';
import { cx } from './Button';
import s from './Popover.module.css';

export interface PopoverProps {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  className?: string;
  style?: CSSProperties;
  label?: string;
}

export function Popover({
  trigger,
  children,
  open,
  onOpenChange,
  side = 'bottom',
  align = 'end',
  className,
  style,
  label,
}: PopoverProps) {
  return (
    <R.Root open={open} onOpenChange={onOpenChange}>
      <R.Trigger asChild>{trigger}</R.Trigger>
      <R.Portal>
        <R.Content
          className={cx(s.content, className)}
          style={style}
          side={side}
          align={align}
          sideOffset={8}
          collisionPadding={12}
          aria-label={label}
        >
          {children}
        </R.Content>
      </R.Portal>
    </R.Root>
  );
}
