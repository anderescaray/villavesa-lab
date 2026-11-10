/** Brand mark: a route polyline ending at a stop, on villavesa red. */
export function BrandMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable="false">
      <rect width="24" height="24" rx="7" fill="var(--accent)" />
      <path
        d="M5.5 15.5 L10 10.5 L13.5 14 L17.5 8.5"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="17.5" cy="8.5" r="2.25" fill="#fff" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span
      style={{
        fontSize: 'var(--text-14)',
        fontWeight: 600,
        letterSpacing: '-0.02em',
        whiteSpace: 'nowrap',
      }}
    >
      villavesa<span style={{ color: 'var(--text-tertiary)', fontWeight: 500 }}> lab</span>
    </span>
  );
}
