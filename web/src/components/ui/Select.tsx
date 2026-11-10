import { Check, ChevronDown } from 'lucide-react';
import { Select as R } from 'radix-ui';
import type { ReactNode } from 'react';
import { cx } from './Button';
import s from './Select.module.css';

export interface SelectOption<T extends string> {
  value: T;
  label: ReactNode;
}

export interface SelectProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  label: string;
  size?: 'sm' | 'md';
  variant?: 'outline' | 'ghost';
  side?: 'top' | 'bottom';
  className?: string;
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  size = 'md',
  variant = 'outline',
  side = 'bottom',
  className,
}: SelectProps<T>) {
  return (
    <R.Root value={value} onValueChange={(v) => onChange(v as T)}>
      <R.Trigger
        aria-label={label}
        className={cx(
          s.trigger,
          size === 'sm' && s.sm,
          variant === 'ghost' && s.ghostTrigger,
          className,
        )}
      >
        <R.Value />
        <R.Icon asChild>
          <ChevronDown strokeWidth={1.5} />
        </R.Icon>
      </R.Trigger>
      <R.Portal>
        <R.Content className={s.content} position="popper" side={side} sideOffset={6}>
          <R.Viewport className={s.viewport}>
            {options.map((o) => (
              <R.Item key={o.value} value={o.value} className={s.item}>
                <R.ItemText>{o.label}</R.ItemText>
                <R.ItemIndicator className={s.indicator}>
                  <Check strokeWidth={2} />
                </R.ItemIndicator>
              </R.Item>
            ))}
          </R.Viewport>
        </R.Content>
      </R.Portal>
    </R.Root>
  );
}
