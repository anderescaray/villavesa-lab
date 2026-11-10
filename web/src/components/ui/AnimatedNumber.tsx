import { useEffect, useRef } from 'react';
import { easeOutCubic, prefersReducedMotion } from '@/lib/motion';

export interface AnimatedNumberProps {
  value: number | null | undefined;
  format: (n: number) => string;
  duration?: number;
  className?: string;
  /** Text when value is null/undefined. */
  placeholder?: string;
}

/**
 * Number that tweens to its new value (no React re-render per frame: writes textContent).
 * Respects prefers-reduced-motion.
 */
export function AnimatedNumber({
  value,
  format,
  duration = 450,
  className,
  placeholder = '—',
}: AnimatedNumberProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const current = useRef<number | null>(null);
  const formatRef = useRef(format);
  formatRef.current = format;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (value === null || value === undefined || !Number.isFinite(value)) {
      el.textContent = placeholder;
      current.current = null;
      return;
    }
    const from = current.current;
    if (from === null || prefersReducedMotion() || from === value) {
      el.textContent = formatRef.current(value);
      current.current = value;
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const v = from + (value - from) * easeOutCubic(p);
      current.current = v;
      el.textContent = formatRef.current(p < 1 ? v : value);
      if (p < 1) raf = requestAnimationFrame(step);
      else current.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration, placeholder]);

  // keep the formatted text in sync when only the formatter (e.g. locale) changes
  useEffect(() => {
    const el = ref.current;
    if (el && current.current !== null) el.textContent = format(current.current);
  }, [format]);

  const initial =
    value === null || value === undefined || !Number.isFinite(value) ? placeholder : format(value);
  return (
    <span ref={ref} className={className} style={{ fontVariantNumeric: 'tabular-nums' }}>
      {initial}
    </span>
  );
}
