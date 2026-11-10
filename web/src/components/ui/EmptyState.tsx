import { Check } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from './Button';
import s from './EmptyState.module.css';

export interface EmptyStateProps {
  icon?: ReactNode;
  eyebrow?: string;
  title: string;
  body?: ReactNode;
  points?: string[];
  actions?: ReactNode;
  compact?: boolean;
}

export function EmptyState({
  icon,
  eyebrow,
  title,
  body,
  points,
  actions,
  compact,
}: EmptyStateProps) {
  return (
    <div className={cx(s.root, compact && s.compact)}>
      {icon ? <span className={s.icon}>{icon}</span> : null}
      <div>
        {eyebrow ? <div className={s.eyebrow}>{eyebrow}</div> : null}
        <h2 className={s.title}>{title}</h2>
      </div>
      {body ? <p className={s.body}>{body}</p> : null}
      {points?.length ? (
        <ul className={s.list}>
          {points.map((p) => (
            <li key={p}>
              <Check strokeWidth={1.75} />
              <span>{p}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {actions ? <div className={s.actions}>{actions}</div> : null}
    </div>
  );
}
