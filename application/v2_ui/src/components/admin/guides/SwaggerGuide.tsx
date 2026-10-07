// SwaggerGuide.tsx
// What the API documentation gives an administrator, and who else can see it.
//
// Ported from the server-rendered page's "Why Enable Swagger?" dialog, with one claim
// corrected: it said the explorer requires an admin sign-in. The Swagger routes are guarded
// by `login_required`, so any signed-in user can open them, and that is the fact an
// administrator weighing whether to publish the API surface needs most.

import { GuideList, GuideNote, GuideSection, Literal } from './GuideDialog';

export function SwaggerGuide({ running }: { running: boolean }) {
    return (
        <>
            <GuideSection title="What it serves">
                <GuideList>
                    <li>
                        <Literal>/swagger</Literal>: an interactive explorer for every route the app
                        registers, with search and filtering. Requests sent from it run with your own
                        session and permissions.
                    </li>
                    <li>
                        <Literal>/swagger.json</Literal> and <Literal>/swagger.yaml</Literal>: the
                        OpenAPI 3 specification the explorer is built from, for client generators and
                        API tools.
                    </li>
                </GuideList>
                <p>
                    The specification is generated from the application&rsquo;s own routes, so it stays
                    current as features are added, and shows which routes require a signed-in session.
                </p>
            </GuideSection>

            <GuideSection title="Why turn it on">
                <GuideList>
                    <li>Developers integrating with SimpleChat can find routes and request shapes themselves.</li>
                    <li>Requests can be tried from the browser while debugging, without separate tooling.</li>
                    <li>Administrators can review the API surface and its authentication requirements.</li>
                </GuideList>
            </GuideSection>

            <GuideSection title="Who can see it">
                <GuideNote tone="warning">
                    Any signed-in user can open these pages, not only administrators. There is no
                    admin-only mode: turn it off if you would rather not publish the API surface to
                    everyone who can sign in.
                </GuideNote>
                <GuideList>
                    <li>The specification is cached on the server.</li>
                    <li>
                        <Literal>/swagger.json</Literal> and <Literal>/swagger.yaml</Literal> answer at most
                        30 requests a minute from each client address.
                    </li>
                </GuideList>
            </GuideSection>

            <GuideSection title="Turning it on or off">
                <p>
                    The routes are registered when the App Service starts, so a saved change takes effect
                    after a restart. {running
                        ? 'This app is serving them now.'
                        : 'This app is not serving them now.'}
                </p>
            </GuideSection>
        </>
    );
}
