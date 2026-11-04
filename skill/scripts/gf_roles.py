#!/usr/bin/env python3
"""The one table of the nine research roles: display name, ids, pillar and brief. Standard library only."""
from __future__ import annotations
from dataclasses import dataclass
import re

RESEARCH_TOOLS = ("WebSearch", "WebFetch", "Read", "Grep", "Glob")  # no shell or write tools


@dataclass(frozen=True)
class Role:
    key: str
    display: str
    pillar: str | None  # None for the red team
    brief: str
    tools: tuple[str, ...] = RESEARCH_TOOLS

    @property
    def claude_id(self):
        return f"gf-{self.key}"

    @property
    def codex_id(self):
        return f"gf_{self.key}"


ROLES: tuple[Role, ...] = (
 Role('problem', 'Problem Discovery', 'problem', 'Research customer pain, urgency, recurrence, status quo, past workarounds, and evidence that target buyers actually experience the pain. Challenge complaints and hypothetical demand.'),
 Role('market', 'Market & ICP', 'market', 'Define user/buyer/payer and initial niche. Research eligible population with original datasets. Derive bottom-up TAM, SAM and reachable SOM low/base/high with units, dates, and cited inputs. Reject grandiose top-down market figures.'),
 Role('value', 'Customer Value', 'value', 'Research the actual job, existing workflow, switching cost, time-to-value, customer-important difference, and reason to move from the current alternative. Separate feature differentiation from observed preference.'),
 Role('economics', 'Unit Economics', 'economics', 'Verify current competitor pricing with direct URLs and tier units, model delivery and support costs, pricing scenarios, margins, break-even, cash conversion, and CAC envelope; mark churn, CAC and willingness to pay unknown until measured.'),
 Role('distribution', 'Distribution & GTM', 'distribution', "Identify first 10 plausible buyer archetypes, lead source and budget authority, channel accessibility, purchasing journey and bottlenecks, and the most credible small test of acquisition costs and conversion. Don't claim funnel metrics without observed data."),
 Role('competition', 'Competitive Intelligence', 'competition', 'Identify direct and indirect alternatives, incumbents, DIY tools, the do-nothing option, current prices and published positioning, bundling risk, switching costs, and credible durable moat. Check company status and distinguish documented facts from claims.'),
 Role('execution', 'Execution & Founder Fit', 'execution', 'Outline a minimal feasible pilot, technical and operational dependencies, data rights, security, licensing, regulatory issues, cost and expert gaps. Treat founder resources as unknown unless supplied. Cite authoritative technical/regulatory sources and avoid legal approval claims.'),
 Role('timing', 'Timing & Survivability', 'timing', "Investigate dated technology and market catalysts, buying windows, regulatory shifts, budget constraints, macro tailwinds and headwinds, platform dependency and believable adjacent expansion. Challenge why it hasn't worked before and whether now is too early or late."),
 Role('redteam', 'Independent Red Team', None, 'Run only after the specialist research is complete. Produce the strongest rejection thesis plus two independent failure modes, challenge original sources and model math, find underweighted competitors, expose unsupported behavior assumptions, classify fatal vs fixable risks, and specify the observation that would reverse the recommendation.'),
)
SPECIALISTS = ROLES[:-1]
REDTEAM = ROLES[-1]
BY_ID = {i: r for r in ROLES for i in (r.claude_id, r.codex_id)}
# Kept in the order of the first release so the installed hook matcher string never changes.
_HOOK_ORDER = "problem market competition economics value distribution execution timing redteam".split()


def normalize(name):
    """Return the Role for gf-x / gf_x in any case, else None."""
    return BY_ID.get(name.strip().lower()) if isinstance(name, str) else None


def hook_matcher():
    by_key = {r.key: r for r in ROLES}
    return "^gf[-_](" + "|".join(re.escape(by_key[k].key) for k in _HOOK_ORDER) + ")$"
