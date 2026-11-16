// EnhancedExtractionEngine.tsx
// Says which engine backs Enhanced extraction, judged from the settings on screen.
//
// Enhanced extraction runs on Azure AI Content Understanding where the service is offered
// and connected, and on Document Intelligence Layout otherwise. Only Content Understanding
// describes figures and charts, yet nothing on the card used to say which was in force, so
// the Enhanced switch and the Content Understanding connection read as unrelated settings.
// This names the engine, and when it is the fallback, why, and what would change it.

import { clsx } from 'clsx';
import { AlertCircle, CheckCircle2, Info } from 'lucide-react';
import type { EnhancedExtractionEngineReading } from '../../lib/enhancedExtraction';

interface EnhancedExtractionEngineProps {
    label: string;
    help?: string;
    reading: EnhancedExtractionEngineReading;
    /** The reading rests on edits that are not saved yet, so it is not in force. */
    pending?: boolean;
}

interface EngineCopy {
    title: string;
    detail: string;
}

function describe(reading: EnhancedExtractionEngineReading): EngineCopy {
    if (reading.engine === 'content_understanding') {
        return {
            title: 'Azure AI Content Understanding',
            detail:
                'Documents extracted as Enhanced get tables, page structure, checkbox states ' +
                'and descriptions of figures and charts. If the service cannot be reached, a ' +
                'document falls back to Document Intelligence Layout and the reason is ' +
                'recorded on it.',
        };
    }

    switch (reading.reason) {
        case 'unsupported_cloud':
            return {
                title: 'Document Intelligence Layout',
                detail:
                    'Azure AI Content Understanding is not offered in this Azure cloud. Layout ' +
                    'captures tables, page structure, forms and checkbox states, but does not ' +
                    'describe figures or charts. There is nothing more to configure.',
            };
        case 'missing_key':
            return {
                title: 'Document Intelligence Layout',
                detail:
                    'Content Understanding has an endpoint but no key. Add the key, or set ' +
                    'Authentication Type to Managed Identity, to use it. Until then figures ' +
                    'and charts are not described.',
            };
        default:
            return {
                title: 'Document Intelligence Layout',
                detail:
                    'Layout captures tables, page structure, forms and checkbox states, but ' +
                    'does not describe figures or charts. Add a Foundry endpoint under ' +
                    'Content Understanding connection to use Azure AI Content Understanding ' +
                    'instead.',
            };
    }
}

export function EnhancedExtractionEngine({
    label,
    help,
    reading,
    pending,
}: EnhancedExtractionEngineProps) {
    const tone =
        reading.engine === 'content_understanding'
            ? 'ok'
            : reading.reason === 'unsupported_cloud'
              ? 'neutral'
              : 'warn';
    const Icon = tone === 'ok' ? CheckCircle2 : tone === 'warn' ? AlertCircle : Info;
    const { title, detail } = describe(reading);

    return (
        <div
            className="admin-field py-3"
            data-field-width="wide"
            data-testid="enhanced-extraction-engine"
            data-engine={reading.engine}
        >
            <div className="admin-field-heading text-sm font-semibold text-text-1">{label}</div>
            {help ? (
                <p className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">{help}</p>
            ) : null}
            <div className="admin-field-control min-w-0">
                <div
                    role="status"
                    aria-live="polite"
                    className={clsx(
                        'flex items-start gap-2.5 rounded-lg border p-3 text-xs leading-relaxed text-text-2',
                        tone === 'ok' && 'border-ok/40 bg-ok/5',
                        tone === 'warn' && 'border-warn/40 bg-warn-soft',
                        tone === 'neutral' && 'border-edge bg-surface-1',
                    )}
                >
                    <Icon
                        size={15}
                        aria-hidden="true"
                        className={clsx(
                            'mt-0.5 shrink-0',
                            tone === 'ok' && 'text-ok',
                            tone === 'warn' && 'text-warn',
                            tone === 'neutral' && 'text-text-3',
                        )}
                    />
                    <div className="min-w-0">
                        <p className="font-medium text-text-1">{title}</p>
                        <p className="mt-1">{detail}</p>
                        {pending ? (
                            <p className="mt-1.5 text-text-3">Takes effect when you save.</p>
                        ) : null}
                    </div>
                </div>
            </div>
        </div>
    );
}
