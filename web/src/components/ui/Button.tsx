import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Tooltip } from './Tooltip';
import s from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const cx = (...c: (string | false | undefined | null)[]) => c.filter(Boolean).join(' ');
export { cx };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(s.button, s[variant], size === 'sm' && s.sm, className)}
      {...rest}
    />
  );
});

export interface IconButtonProps extends ButtonProps {
  /** Accessible name, also shown as tooltip. */
  label: string;
  /** Optional keyboard hint shown in the tooltip. */
  shortcut?: string;
  pressed?: boolean;
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left';
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, shortcut, pressed, variant = 'ghost', size = 'md', className, tooltipSide, ...rest },
  ref,
) {
  return (
    <Tooltip content={label} shortcut={shortcut} side={tooltipSide}>
      <Button
        ref={ref}
        aria-label={label}
        aria-pressed={pressed}
        variant={variant}
        size={size}
        className={cx(s.icon, pressed && s.pressed, className)}
        {...rest}
      />
    </Tooltip>
  );
});
