/** Shared motion constants (mirrors tokens.css) and helpers. */
export const DURATION = { fast: 150, base: 200, slow: 250 } as const;

/** cubic-bezier(0.16, 1, 0.3, 1) ≈ easeOutExpo-ish; a cheap analytic approximation. */
export const easeOutCubic = (t: number) => 1 - (1 - t) ** 3;

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  );
}
