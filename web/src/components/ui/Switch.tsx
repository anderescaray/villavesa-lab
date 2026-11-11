import { Switch as R } from 'radix-ui';
import { useId, type ReactNode } from 'react';
import s from './Switch.module.css';

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children?: ReactNode;
  label?: string;
}

export function Switch({ checked, onChange, children, label }: SwitchProps) {
  const id = useId();
  return (
    <label className={s.row} htmlFor={id}>
      <R.Root
        id={id}
        className={s.root}
        checked={checked}
        onCheckedChange={onChange}
        aria-label={label}
      >
        <R.Thumb className={s.thumb} />
      </R.Root>
      {children}
    </label>
  );
}
