// sectionStatusContext.ts
// The status of the section a field is drawn in, for controls that react to it.
//
// A section's status is computed once by the page and shown on the card. A field control
// sometimes needs the same answer: the Required marker on an empty required field only
// helps while its section reads "Needs configuration". Blank fields under a switched-off
// capability are not a problem to solve, and marking them would contradict the card.
// Providing the status through context keeps every renderer's signature unchanged.

import { createContext } from 'react';
import type { SectionStatus } from '../../lib/adminSections';

/** Undefined outside a section card, where a control decides on the field alone. */
export const SectionStatusContext = createContext<SectionStatus | undefined>(undefined);
