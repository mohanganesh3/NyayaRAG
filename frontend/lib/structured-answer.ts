export type StructuredAnswerBadgeStatus =
  | "VERIFIED"
  | "UNCERTAIN"
  | "UNVERIFIED";

export type StructuredAnswerSectionKind =
  | "LEGAL_POSITION"
  | "APPLICABLE_LAW"
  | "KEY_CASES"
  | "VERIFICATION_STATUS";

export type InlineCitationBadge = {
  appealWarning: string | null;
  chunkId: string | null;
  citation: string | null;
  docId: string | null;
  label: string;
  message: string;
  placeholderToken: string;
  sourcePassage: string | null;
  status: StructuredAnswerBadgeStatus;
};

export type StructuredClaim = {
  appealWarning: string | null;
  citation: string | null;
  citationBadges: InlineCitationBadge[];
  reason: string;
  reretrieved: boolean;
  sourcePassage: string | null;
  status: StructuredAnswerBadgeStatus;
  text: string;
};

export type VerificationStatusItem = {
  label: string;
  status: StructuredAnswerBadgeStatus;
  value: string;
};

export type StructuredAnswerSection = {
  kind: StructuredAnswerSectionKind;
  title: string;
  claims: StructuredClaim[];
  statusItems: VerificationStatusItem[];
};

export type StructuredAnswer = {
  overallStatus: StructuredAnswerBadgeStatus;
  query: string;
  sections: StructuredAnswerSection[];
};

export type StructuredAnswerSource = {
  appealWarning: string | null;
  chunkId: string | null;
  citation: string;
  docId: string | null;
  id: string;
  label: string;
  message: string;
  sourcePassage: string | null;
  status: StructuredAnswerBadgeStatus;
};

export function buildStructuredSourceId(input: {
  chunkId: string | null;
  citation: string | null;
  docId: string | null;
  label: string;
}): string {
  return [
    input.docId ?? "",
    input.chunkId ?? "",
    input.citation ?? input.label,
  ].join("::");
}

function sourceIdForBadge(badge: InlineCitationBadge): string {
  return buildStructuredSourceId({
    docId: badge.docId,
    chunkId: badge.chunkId,
    citation: badge.citation,
    label: badge.label,
  });
}

export function collectStructuredAnswerSources(
  answer: StructuredAnswer,
): StructuredAnswerSource[] {
  const seen = new Set<string>();
  const sources: StructuredAnswerSource[] = [];

  for (const section of answer.sections) {
    for (const claim of section.claims) {
      for (const badge of claim.citationBadges) {
        if (!badge.citation && !badge.sourcePassage) {
          continue;
        }

        const id = sourceIdForBadge(badge);
        if (seen.has(id)) {
          continue;
        }

        seen.add(id);
        sources.push({
          id,
          label: badge.label,
          citation: badge.citation ?? badge.label,
          status: badge.status,
          message: badge.message,
          docId: badge.docId,
          chunkId: badge.chunkId,
          sourcePassage: badge.sourcePassage,
          appealWarning: badge.appealWarning,
        });
      }
    }
  }

  return sources;
}

export const demoStructuredAnswer: StructuredAnswer = {
  query:
    "What are the strongest anticipatory bail arguments on these facts, and which binding Supreme Court cases should appear first in the note?",
  overallStatus: "UNCERTAIN",
  sections: [
    {
      kind: "LEGAL_POSITION",
      title: "Legal Position",
      statusItems: [],
      claims: [
        {
          text: "On the present record, the strongest anticipatory bail submission is that the prosecution narrative still looks substantially documentary and commercial, which weakens any immediate custodial justification.",
          status: "VERIFIED",
          reason:
            "Binding anticipatory bail authorities emphasize concrete necessity for custody, not generalized investigation language.",
          citation: "Siddharam Satlingappa Mhetre v State of Maharashtra, (2011) 1 SCC 694",
          sourcePassage:
            "Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters.",
          appealWarning: null,
          reretrieved: false,
          citationBadges: [
            {
              placeholderToken: "[CITE: anticipatory bail liberty authority]",
              label: "Siddharam Satlingappa Mhetre",
              status: "VERIFIED",
              citation:
                "Siddharam Satlingappa Mhetre v State of Maharashtra, (2011) 1 SCC 694",
              message:
                "Verified authority supporting a liberty-first anticipatory bail analysis.",
              docId: "sc-siddharam-2011",
              chunkId: "chunk-3",
              sourcePassage:
                "Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters.",
              appealWarning: null,
            },
            {
              placeholderToken: "[CITE: foundational anticipatory bail bench]",
              label: "Gurbaksh Singh Sibbia",
              status: "VERIFIED",
              citation:
                "Gurbaksh Singh Sibbia v State of Punjab, (1980) 2 SCC 565",
              message:
                "Constitution Bench baseline on anticipatory bail discretion.",
              docId: "sc-sibbia-1980",
              chunkId: "chunk-8",
              sourcePassage:
                "Anticipatory bail must remain flexible and fact-sensitive, but it cannot be denied merely on broad prosecutorial assertions.",
              appealWarning: null,
            },
          ],
        },
        {
          text: "The prosecution will still argue that financial-trail recovery and witness coordination demand custodial access, so the defense must foreground cooperation and document production.",
          status: "UNCERTAIN",
          reason:
            "The cited arrest-guideline authority is relevant, but factual parity depends on the prosecution's current material.",
          citation: "Arnesh Kumar v State of Bihar, (2014) 8 SCC 273",
          sourcePassage:
            "Arrest cannot be routine, and the investigating officer must justify why custody is necessary on the facts of the case.",
          appealWarning: null,
          reretrieved: true,
          citationBadges: [
            {
              placeholderToken: "[CITE: arrest restraint authority]",
              label: "Arnesh Kumar",
              status: "UNCERTAIN",
              citation: "Arnesh Kumar v State of Bihar, (2014) 8 SCC 273",
              message:
                "Useful arrest-restraint authority, but still needs fact-specific application to this record.",
              docId: "sc-arnesh-2014",
              chunkId: "chunk-2",
              sourcePassage:
                "Arrest cannot be routine, and the investigating officer must justify why custody is necessary on the facts of the case.",
              appealWarning: null,
            },
          ],
        },
      ],
    },
    {
      kind: "APPLICABLE_LAW",
      title: "Applicable Law",
      statusItems: [],
      claims: [
        {
          text: "For a post-July 2024 analysis, the anticipatory bail reference point is BNSS Section 482, even if the FIR and draft pleadings still use the older CrPC 438 vocabulary.",
          status: "VERIFIED",
          reason:
            "The workspace already maps legacy criminal procedure references to the new criminal code regime.",
          citation: "BNSS Section 482",
          sourcePassage:
            "BNSS Section 482 carries forward the anticipatory bail framework for the post-cutover criminal procedure regime.",
          appealWarning: null,
          reretrieved: false,
          citationBadges: [
            {
              placeholderToken: "[STATUTE: BNSS, Section 482]",
              label: "BNSS 482",
              status: "VERIFIED",
              citation: "Bharatiya Nagarik Suraksha Sanhita, 2023, Section 482",
              message: "Current anticipatory bail provision for post-cutover analysis.",
              docId: "bnss-482",
              chunkId: "section-482",
              sourcePassage:
                "BNSS Section 482 carries forward the anticipatory bail framework for the post-cutover criminal procedure regime.",
              appealWarning: null,
            },
          ],
        },
        {
          text: "The cheating and breach-of-trust allegations also need to be tracked against BNS Sections 318 and 316 so the note stays temporally current.",
          status: "VERIFIED",
          reason:
            "Temporal validity and code mapping are part of the system's statutory verification path.",
          citation: "BNS Sections 318 and 316",
          sourcePassage:
            "The new penal code provisions preserve the operative cheating and breach-of-trust categories while changing section numbering.",
          appealWarning: null,
          reretrieved: false,
          citationBadges: [
            {
              placeholderToken: "[STATUTE: BNS, Section 318]",
              label: "BNS 318",
              status: "VERIFIED",
              citation: "Bharatiya Nyaya Sanhita, 2023, Section 318",
              message: "Mapped from IPC 420 for post-cutover treatment.",
              docId: "bns-318",
              chunkId: "section-318",
              sourcePassage:
                "The new penal code provisions preserve the operative cheating categories while changing section numbering.",
              appealWarning: null,
            },
            {
              placeholderToken: "[STATUTE: BNS, Section 316]",
              label: "BNS 316",
              status: "VERIFIED",
              citation: "Bharatiya Nyaya Sanhita, 2023, Section 316",
              message: "Mapped from IPC 406 for post-cutover treatment.",
              docId: "bns-316",
              chunkId: "section-316",
              sourcePassage:
                "The new penal code provisions preserve the operative breach-of-trust categories while changing section numbering.",
              appealWarning: null,
            },
          ],
        },
      ],
    },
    {
      kind: "KEY_CASES",
      title: "Key Cases",
      statusItems: [],
      claims: [
        {
          text: "Siddharam Satlingappa Mhetre should lead the note because it gives the cleanest liberty-first framework for anticipatory bail where the State has not yet justified custody with precision.",
          status: "VERIFIED",
          reason: "Best binding fit for the current bail posture.",
          citation:
            "Siddharam Satlingappa Mhetre v State of Maharashtra, (2011) 1 SCC 694",
          sourcePassage:
            "Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters.",
          appealWarning: null,
          reretrieved: false,
          citationBadges: [
            {
              placeholderToken: "[CITE: lead anticipatory bail authority]",
              label: "Siddharam Satlingappa Mhetre",
              status: "VERIFIED",
              citation:
                "Siddharam Satlingappa Mhetre v State of Maharashtra, (2011) 1 SCC 694",
              message: "Lead binding authority for this answer.",
              docId: "sc-siddharam-2011",
              chunkId: "chunk-3",
              sourcePassage:
                "Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters.",
              appealWarning: null,
            },
          ],
        },
        {
          text: "Gurbaksh Singh Sibbia remains the foundational Constitution Bench authority on how anticipatory bail discretion should be exercised without reducing the remedy to a rarity.",
          status: "VERIFIED",
          reason: "Foundational binding authority with continuing precedential weight.",
          citation: "Gurbaksh Singh Sibbia v State of Punjab, (1980) 2 SCC 565",
          sourcePassage:
            "Anticipatory bail must remain flexible and fact-sensitive, but it cannot be denied merely on broad prosecutorial assertions.",
          appealWarning: null,
          reretrieved: false,
          citationBadges: [
            {
              placeholderToken: "[CITE: foundational anticipatory bail case]",
              label: "Gurbaksh Singh Sibbia",
              status: "VERIFIED",
              citation:
                "Gurbaksh Singh Sibbia v State of Punjab, (1980) 2 SCC 565",
              message: "Foundational Constitution Bench authority.",
              docId: "sc-sibbia-1980",
              chunkId: "chunk-8",
              sourcePassage:
                "Anticipatory bail must remain flexible and fact-sensitive, but it cannot be denied merely on broad prosecutorial assertions.",
              appealWarning: null,
            },
          ],
        },
      ],
    },
    {
      kind: "VERIFICATION_STATUS",
      title: "Verification Status",
      claims: [],
      statusItems: [
        {
          label: "Verified Claims",
          value: "5",
          status: "VERIFIED",
        },
        {
          label: "Claims Requiring Review",
          value: "1",
          status: "UNCERTAIN",
        },
        {
          label: "Unverified Claims",
          value: "0",
          status: "VERIFIED",
        },
        {
          label: "Resolved Citations",
          value: "6",
          status: "VERIFIED",
        },
        {
          label: "Unresolved Citations",
          value: "0",
          status: "VERIFIED",
        },
      ],
    },
  ],
};
