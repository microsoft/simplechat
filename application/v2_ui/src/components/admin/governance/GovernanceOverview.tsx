// GovernanceOverview.tsx
// How governance decides, stated once at the top of the Governance group.
//
// The classic page explained this in a six-tab modal, and one of its statements was wrong:
// it said an empty allow list was permissive, when the server refuses everyone. This is the
// short, correct version. The two-layer summary stays visible; how a request is checked
// opens on demand, so the switches below remain the first thing on the card.

import { useState } from 'react';
import { clsx } from 'clsx';
import { ChevronRight, ExternalLink } from 'lucide-react';

const GOVERNANCE_GUIDE_URL = 'https://microsoft.github.io/simplechat/admin/governance/';

export function GovernanceOverview() {
    const [open, setOpen] = useState(false);

    return (
        <div className="py-3 text-[0.8125rem] leading-relaxed">
            <p className="max-w-[80ch] text-text-2">
                Governance decides who may use what is configured inside SimpleChat; Entra app roles still decide
                who may sign in. A <span className="font-semibold text-text-1">feature policy</span> decides who may
                use a kind of capability, such as personal agents. A{' '}
                <span className="font-semibold text-text-1">delegated item policy</span> decides who may use one
                specific resource. Block lists always win.
            </p>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                <button
                    type="button"
                    aria-expanded={open}
                    aria-controls="governance-evaluation-order"
                    onClick={() => setOpen((current) => !current)}
                    className="inline-flex items-center gap-1 rounded-md py-0.5 text-xs font-medium text-accent hover:underline"
                >
                    <ChevronRight size={13} aria-hidden="true" className={clsx('transition-transform', open && 'rotate-90')} />
                    How a request is checked
                </button>
                <a
                    href={GOVERNANCE_GUIDE_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                >
                    Read the governance guide
                    <ExternalLink size={12} aria-hidden="true" />
                    <span className="sr-only">(opens in a new tab)</span>
                </a>
            </div>

            {open ? (
                <div id="governance-evaluation-order" className="mt-2 max-w-[80ch] space-y-2 text-text-3">
                    <ol className="list-decimal space-y-1 pl-5">
                        <li>A governance switch that is off checks nothing.</li>
                        <li>A block list that names the person, or one of their groups, refuses them.</li>
                        <li>
                            The feature policy must allow them: everyone, or a list that names them or one of their
                            groups. With Allow everyone off and nobody listed, nobody passes.
                        </li>
                        <li>
                            For a specific resource, passing any one of its item policies is enough, and with none
                            the feature policy decides alone. An item policy cannot open a feature the feature
                            policy refuses, with one exception: an action type with its own policies requires one of
                            them, and can be opened to people the feature policy leaves out.
                        </li>
                    </ol>
                    <p>
                        MCP destinations and inbound MCP sources work the other way round: with no policy, nothing
                        is allowed.
                    </p>
                    <p>
                        A group or public workspace in a policy stands for its members, so it works as a reusable
                        cohort, such as the people piloting personal agents. It grants nothing inside that workspace.
                    </p>
                </div>
            ) : null}
        </div>
    );
}
