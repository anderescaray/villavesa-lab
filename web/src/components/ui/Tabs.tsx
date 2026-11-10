import { Tabs as R } from 'radix-ui';
import type { ReactNode } from 'react';
import s from './Tabs.module.css';

export interface TabsProps<T extends string> {
  value: T;
  onChange: (v: T) => void;
  tabs: readonly { value: T; label: ReactNode }[];
  label: string;
  children?: ReactNode;
}

export function Tabs<T extends string>({ value, onChange, tabs, label, children }: TabsProps<T>) {
  return (
    <R.Root value={value} onValueChange={(v) => onChange(v as T)}>
      <R.List className={s.list} aria-label={label}>
        {tabs.map((tab) => (
          <R.Trigger key={tab.value} value={tab.value} className={s.trigger}>
            {tab.label}
          </R.Trigger>
        ))}
      </R.List>
      {children}
    </R.Root>
  );
}

export const TabPanel = R.Content;
