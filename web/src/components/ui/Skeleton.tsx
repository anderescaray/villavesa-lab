import type { CSSProperties } from 'react';
import { cx } from './Button';
import s from './Skeleton.module.css';

export function Skeleton({
  width = '100%',
  height = 12,
  radius,
  className,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      aria-hidden
      className={cx(s.skeleton, className)}
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}
