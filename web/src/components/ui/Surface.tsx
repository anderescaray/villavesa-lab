import { forwardRef, type HTMLAttributes } from 'react';
import { cx } from './Button';
import s from './Surface.module.css';

/** Floating surface over the map: raised background, hairline ring, one soft shadow. */
export const Surface = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function Surface(
  { className, ...rest },
  ref,
) {
  return <div ref={ref} className={cx(s.surface, className)} {...rest} />;
});
