import { useMemo, type HTMLAttributes, type ReactNode } from 'react';
import { contrastRatio, readableTextOn } from '@/lib/color';
import { cx } from './Button';
import s from './Badge.module.css';

export function Badge({
  children,
  tone = 'neutral',
  className,
  ...rest
}: { children: ReactNode; tone?: 'neutral' | 'accent' } & HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cx(s.badge, tone === 'accent' && s.accent, className)} {...rest}>
      {children}
    </span>
  );
}

export interface LineBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  shortName: string;
  color: string;
  textColor?: string;
  size?: 'sm' | 'md' | 'lg';
}

/** Line chip in the operator's GTFS colour, with AA-contrast text. */
export function LineBadge({
  shortName,
  color,
  textColor,
  size = 'md',
  className,
  ...rest
}: LineBadgeProps) {
  const fg = useMemo(() => readableTextOn(color, textColor), [color, textColor]);
  const ring = useMemo(() => contrastRatio(color, '#FFFFFF') < 1.4, [color]);
  return (
    <span
      className={cx(
        s.line,
        size === 'lg' && s.lineLg,
        size === 'sm' && s.lineSm,
        ring && s.ring,
        className,
      )}
      style={{ background: color, color: fg }}
      {...rest}
    >
      {shortName}
    </span>
  );
}
