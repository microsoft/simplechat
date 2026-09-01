// primitives.tsx
// Shared glass UI building blocks used across the V2 interface.

import { clsx } from 'clsx';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

type PanelElevation = 'flat' | 'glass' | 'raised';

const elevationClass: Record<PanelElevation, string> = {
    // `glass-flat` skips backdrop-filter, which matters for anything repeated in a list.
    flat: 'glass-flat',
    glass: 'glass',
    raised: 'glass-raised',
};

interface GlassPanelProps extends HTMLAttributes<HTMLDivElement> {
    elevation?: PanelElevation;
    /** Adds the specular top highlight. Decorative only. */
    edge?: boolean;
    children?: ReactNode;
}

export function GlassPanel({
    elevation = 'glass',
    edge = false,
    className,
    children,
    ...rest
}: GlassPanelProps) {
    return (
        <div
            className={clsx(
                elevationClass[elevation],
                edge && 'glass-edge',
                'rounded-2xl',
                className,
            )}
            {...rest}
        >
            {children}
        </div>
    );
}

type ButtonVariant = 'primary' | 'ghost' | 'subtle' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

const variantClass: Record<ButtonVariant, string> = {
    primary:
        'bg-accent text-on-accent hover:bg-accent-hover shadow-sm disabled:hover:bg-accent',
    ghost: 'text-text-2 hover:text-text-1 hover:bg-surface-2',
    subtle: 'glass-flat text-text-1 hover:bg-surface-2 rounded-xl',
    danger: 'bg-danger-soft text-danger hover:bg-danger hover:text-white',
};

const sizeClass: Record<ButtonSize, string> = {
    sm: 'h-8 px-3 text-sm gap-1.5',
    md: 'h-10 px-4 text-sm gap-2',
    lg: 'h-12 px-6 text-base gap-2',
    icon: 'h-9 w-9 justify-center',
};

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant;
    size?: ButtonSize;
    children?: ReactNode;
}

export function GlassButton({
    variant = 'ghost',
    size = 'md',
    className,
    children,
    ...rest
}: GlassButtonProps) {
    return (
        <button
            className={clsx(
                'inline-flex items-center rounded-xl font-medium transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-50',
                variantClass[variant],
                sizeClass[size],
                className,
            )}
            {...rest}
        >
            {children}
        </button>
    );
}

/**
 * A labelled on/off control. Rendered as a real checkbox input so it is keyboard
 * operable and announced correctly, with the visual switch drawn from sibling elements.
 */
export function Toggle({
    checked,
    onChange,
    label,
    description,
    disabled = false,
}: {
    checked: boolean;
    onChange: (next: boolean) => void;
    label: string;
    description?: string;
    disabled?: boolean;
}) {
    return (
        <label
            className={clsx(
                'flex items-start gap-3 py-2',
                disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
            )}
        >
            <span className="relative mt-0.5 inline-flex shrink-0">
                <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={checked}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.checked)}
                />
                <span
                    aria-hidden="true"
                    className={clsx(
                        'block h-6 w-11 rounded-full border transition-colors',
                        'border-edge bg-surface-sunken',
                        'peer-checked:border-transparent peer-checked:bg-accent',
                        'peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-2',
                    )}
                />
                <span
                    aria-hidden="true"
                    className={clsx(
                        'pointer-events-none absolute top-1 left-1 h-4 w-4 rounded-full',
                        'bg-white shadow transition-transform duration-200',
                        'peer-checked:translate-x-5',
                    )}
                />
            </span>
            <span className="min-w-0">
                <span className="block text-sm font-medium text-text-1">{label}</span>
                {description ? (
                    <span className="mt-0.5 block text-xs leading-relaxed text-text-3">
                        {description}
                    </span>
                ) : null}
            </span>
        </label>
    );
}

export function Skeleton({ className }: { className?: string }) {
    return (
        <div
            aria-hidden="true"
            className={clsx('animate-pulse rounded-lg bg-surface-sunken', className)}
        />
    );
}

/**
 * Marks UI that is intentionally present but not yet connected to the API. Being explicit
 * beats a control that silently does nothing.
 */
export function NotWiredBadge({ className }: { className?: string }) {
    return (
        <span
            className={clsx(
                'rounded-full border border-edge bg-warn-soft px-1.5 py-0.5',
                'text-[10px] leading-none font-semibold tracking-wide text-warn uppercase',
                className,
            )}
            title="This control is part of the V2 design but is not wired to the API yet."
        >
            Preview
        </span>
    );
}

export function EmptyState({
    icon,
    title,
    description,
    action,
}: {
    icon?: ReactNode;
    title: string;
    description?: string;
    action?: ReactNode;
}) {
    return (
        <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
            {icon ? <div className="mb-4 text-text-3">{icon}</div> : null}
            <p className="text-base font-medium text-text-1">{title}</p>
            {description ? (
                <p className="mt-1 max-w-md text-sm text-text-3">{description}</p>
            ) : null}
            {action ? <div className="mt-4">{action}</div> : null}
        </div>
    );
}
