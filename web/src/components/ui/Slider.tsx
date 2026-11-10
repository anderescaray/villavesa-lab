import { Slider as R } from 'radix-ui';
import { cx } from './Button';
import s from './Slider.module.css';

export interface SliderProps {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  label: string;
  valueText?: string;
  className?: string;
}

export function Slider({
  value,
  onChange,
  min,
  max,
  step = 1,
  label,
  valueText,
  className,
}: SliderProps) {
  return (
    <R.Root
      className={cx(s.root, className)}
      value={[value]}
      min={min}
      max={max}
      step={step}
      onValueChange={([v]) => v !== undefined && onChange(v)}
    >
      <R.Track className={s.track}>
        <R.Range className={s.range} />
      </R.Track>
      <R.Thumb className={s.thumb} aria-label={label} aria-valuetext={valueText} />
    </R.Root>
  );
}
