// HealthCheckGuide.tsx
// How to point Azure App Service, or another monitor, at SimpleChat's health endpoints.
//
// Ported from the server-rendered page's Configuration Guide, with its response examples
// replaced. That guide documented a JSON body with per-dependency checks and an HTTP 503
// for an unhealthy app; neither route returns anything of the kind. `/external/healthcheck`
// answers with the server time as text, `/external/healthcheckz` with a two-field JSON
// status, and either answers HTTP 400 while it is switched off. A monitor configured
// against the documented shape would have been waiting for a response that never comes.

import { asBoolean } from '../../../lib/adminFields';
import { safeSameOriginUrl } from '../../../lib/adminOperations';
import { apiUrl } from '../../../lib/apiClient';
import type { Json } from '../../../lib/types';
import { CopyButton } from '../CopyValue';
import {
    GuideCode,
    GuideIssue,
    GuideLinks,
    GuideNote,
    GuideSection,
    GuideSteps,
    Literal,
    UiName,
} from './GuideDialog';

const ENDPOINTS = [
    {
        path: '/external/healthcheck',
        key: 'enable_external_healthcheck',
        name: 'Authenticated check',
        answer: 'HTTP 200 with the server time as text.',
        example: '2026-10-06 17:45:33',
        // `enabled_required` builds the message from the setting key, so each route names its own.
        disabled: '{"error": "Enable External Healthcheck is disabled."}',
    },
    {
        path: '/external/healthcheckz',
        key: 'enable_no_auth_external_healthcheck',
        name: 'Unauthenticated check',
        answer: 'HTTP 200 with a small JSON status.',
        example: '{\n  "status": "ok",\n  "time": "2026-10-06 17:45:33"\n}',
        disabled: '{"error": "Enable No Auth External Healthcheck is disabled."}',
    },
] as const;

export function HealthCheckGuide({ settings }: { settings: Json }) {
    const origin = window.location.origin;

    return (
        <>
            <GuideSection title="What the endpoints check">
                <p>
                    Both confirm that the web app is answering requests and can read its own settings.
                    Neither exercises Azure AI Search, Azure OpenAI or storage, so a failing check points
                    at the app itself rather than at a downstream service.
                </p>
                <ul className="divide-y divide-edge rounded-lg border border-edge">
                    {ENDPOINTS.map((endpoint) => {
                        const url = safeSameOriginUrl(apiUrl(endpoint.path), origin) ?? endpoint.path;
                        const enabled = asBoolean(settings[endpoint.key]);
                        return (
                            <li key={endpoint.path} className="space-y-1.5 px-3 py-2.5">
                                <p className="flex flex-wrap items-center gap-x-2">
                                    <span className="font-semibold text-text-1">{endpoint.name}</span>
                                    <span className="text-xs text-text-3">
                                        {enabled ? 'On in the saved settings' : 'Off in the saved settings'}
                                    </span>
                                </p>
                                <div className="flex min-w-0 items-center gap-1">
                                    <code className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-2 py-1 font-mono text-xs text-text-1">
                                        {url}
                                    </code>
                                    <CopyButton value={url} label={`the ${endpoint.name.toLowerCase()} address`} />
                                </div>
                                <p>{endpoint.answer}</p>
                                <GuideCode code={endpoint.example} label={`the ${endpoint.name.toLowerCase()} example`} />
                                <p className="text-xs text-text-3">
                                    Switched off, it answers HTTP 400 with <Literal>{endpoint.disabled}</Literal>
                                </p>
                            </li>
                        );
                    })}
                </ul>
            </GuideSection>

            <GuideSection title="Set up App Service Health check">
                <GuideSteps>
                    <li>
                        Turn on <UiName>Enable /external/healthcheck</UiName> here and save first, so the
                        path answers before App Service starts asking.
                    </li>
                    <li>
                        In the Azure portal, open the App Service and select <UiName>Health check</UiName>{' '}
                        under <UiName>Monitoring</UiName>.
                    </li>
                    <li className="space-y-1.5">
                        <p>
                            Select <UiName>Enable</UiName>, enter this path, and select <UiName>Save</UiName>.
                        </p>
                        <GuideCode code="/external/healthcheck" label="the health check path" />
                    </li>
                </GuideSteps>
                <GuideNote>
                    The bundled deployers already set this path. App Service&rsquo;s own checks work with
                    App Service Authentication turned on.
                </GuideNote>
                <GuideNote tone="warning">
                    If the path stays configured while the endpoint is switched off here, every check gets
                    HTTP 400 and App Service starts treating its instances as unhealthy.
                </GuideNote>
            </GuideSection>

            <GuideSection title="Probes that cannot sign in">
                <p>
                    Use <Literal>/external/healthcheckz</Literal> for an external monitor or load balancer
                    probe that has no way to authenticate. It answers anyone who can reach the app, so only
                    turn it on for trusted probes or controlled network paths.
                </p>
                <GuideNote>
                    If App Service Authentication requires sign-in for every request, exclude this path
                    there as well, or the probe is turned away before it reaches SimpleChat.
                </GuideNote>
            </GuideSection>

            <GuideSection title="Troubleshooting">
                <GuideIssue symptom="The check returns HTTP 400">
                    <li>The endpoint is switched off in these settings. Turn it on and save.</li>
                </GuideIssue>
                <GuideIssue symptom="An external probe is redirected to sign in, or gets HTTP 401">
                    <li>
                        App Service Authentication is answering before SimpleChat does. Sign the probe in,
                        or point it at <Literal>/external/healthcheckz</Literal> and exclude that path from
                        authentication.
                    </li>
                </GuideIssue>
                <GuideIssue symptom="App Service keeps replacing instances">
                    <li>
                        Confirm the configured path is switched on here, then check the application log
                        stream: a failing check means the app is not answering requests at all.
                    </li>
                </GuideIssue>
            </GuideSection>

            <GuideSection title="Further reading">
                <GuideLinks
                    links={[
                        {
                            label: 'Microsoft Learn: Monitor App Service instances by using Health check',
                            href: 'https://learn.microsoft.com/en-us/azure/app-service/monitor-instances-health-check',
                        },
                    ]}
                />
            </GuideSection>
        </>
    );
}
