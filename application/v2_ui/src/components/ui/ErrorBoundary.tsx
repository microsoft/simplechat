// ErrorBoundary.tsx
// Stops a render error in one view from blanking the whole application.
//
// A single unexpected payload shape (for example a tag arriving as an object where a
// string was expected) previously unmounted the entire React tree, leaving a blank page
// with only a minified console error. Containing the failure keeps the rail usable so the
// user can navigate somewhere else.

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { RotateCcw, TriangleAlert } from 'lucide-react';
import { GlassPanel } from './primitives';

interface Props {
    children: ReactNode;
    /** Changing this resets the boundary, so navigating away clears a failed view. */
    resetKey?: string;
}

interface State {
    error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { error: null };

    static getDerivedStateFromError(error: Error): State {
        return { error };
    }

    componentDidUpdate(previousProps: Props) {
        if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
            this.setState({ error: null });
        }
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        // Kept as console output rather than a toast: this is developer diagnostics, and
        // the user already has the message below.
        console.error('V2 UI render error:', error, info.componentStack);
    }

    render() {
        const { error } = this.state;

        if (!error) {
            return this.props.children;
        }

        return (
            <div className="flex flex-1 items-center justify-center p-6">
                <GlassPanel edge className="max-w-lg p-6">
                    <div className="flex items-start gap-3">
                        <TriangleAlert size={20} className="mt-0.5 shrink-0 text-danger" />
                        <div className="min-w-0">
                            <h2 className="font-semibold text-text-1">This view failed to render</h2>
                            <p className="mt-1 text-sm text-text-3">
                                The rest of the app still works — use the navigation on the left
                                to go elsewhere.
                            </p>
                            <pre className="mt-3 max-h-32 overflow-auto rounded-lg bg-surface-sunken p-2 font-mono text-xs break-words whitespace-pre-wrap text-text-2">
                                {error.message}
                            </pre>
                            <button
                                type="button"
                                onClick={() => this.setState({ error: null })}
                                className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover"
                            >
                                <RotateCcw size={15} />
                                Try again
                            </button>
                        </div>
                    </div>
                </GlassPanel>
            </div>
        );
    }
}
