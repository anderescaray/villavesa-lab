import { ToggleGroup } from 'radix-ui';
import type { ReactNode } from 'react';
import { cx } from './Button';
import { Tooltip } from './Tooltip';
import s from './SegmentedControl.module.css';

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  /** Accessible name when `label` is an icon. */
  ariaLabel?: string;
  tooltip?: string;
}

export interface SegmentedControlProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: readonly SegmentOption<T>[];
  label: string;
  size?: 'sm' | 'md';
  fullWidth?: boolean;
  className?: string;
}

/** Single-select segmented control (roving focus, arrow keys) built on Radix ToggleGroup. */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  label,
  size = 'md',
  fullWidth,
  className,
}: SegmentedControlProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      aria-label={label}
      onValueChange={(v) => v && onChange(v as T)}
      className={cx(s.root, size === 'sm' && s.sm, fullWidth && s.full, className)}
    >
      {options.map((o) => {
        const item = (
          <ToggleGroup.Item
            key={o.value}
            value={o.value}
            aria-label={o.ariaLabel}
            className={s.item}
          >
            {o.label}
          </ToggleGroup.Item>
        );
        return o.tooltip ? (
          <Tooltip key={o.value} content={o.tooltip}>
            {item}
          </Tooltip>
        ) : (
          item
        );
      })}
    </ToggleGroup.Root>
  );
}
