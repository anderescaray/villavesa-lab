import { Tooltip as R } from 'radix-ui';
import type { ReactNode } from 'react';
import s from './Tooltip.module.css';

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <R.Provider delayDuration={350} skipDelayDuration={200}>
      {children}
    </R.Provider>
  );
}

export interface TooltipProps {
  content: ReactNode;
  shortcut?: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
  children: ReactNode;
}

export function Tooltip({ content, shortcut, side = 'bottom', children }: TooltipProps) {
  return (
    <R.Root>
      <R.Trigger asChild>{children}</R.Trigger>
      <R.Portal>
        <R.Content className={s.content} side={side} sideOffset={6} collisionPadding={8}>
          {content}
          {shortcut ? <span className={s.kbd}>{shortcut}</span> : null}
        </R.Content>
      </R.Portal>
    </R.Root>
  );
}
