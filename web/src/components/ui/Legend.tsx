import s from './Legend.module.css';

export interface LegendItem {
  color: string;
  label: string;
}

/** Categorical/ordinal legend: swatch + text in ink colour (never coloured text). */
export function Legend({
  title,
  items,
  variant = 'swatches',
}: {
  title?: string;
  items: LegendItem[];
  variant?: 'swatches' | 'ramp';
}) {
  if (variant === 'ramp') {
    return (
      <div className={s.legend}>
        {title ? <div className={s.title}>{title}</div> : null}
        <div className={s.ramp} aria-hidden>
          {items.map((i) => (
            <span key={i.label} style={{ background: i.color }} />
          ))}
        </div>
        <div className={s.rampLabels}>
          {items.map((i) => (
            <span key={i.label}>{i.label}</span>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className={s.legend}>
      {title ? <div className={s.title}>{title}</div> : null}
      <div className={s.items}>
        {items.map((i) => (
          <span key={i.label} className={s.item}>
            <span className={s.swatch} style={{ background: i.color }} aria-hidden />
            {i.label}
          </span>
        ))}
      </div>
    </div>
  );
}
