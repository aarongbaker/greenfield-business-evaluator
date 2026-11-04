"""Business-model policy profiles (transparent judgment heuristics, not predictions)."""
BASE={'problem':20,'market':15,'value':15,'economics':15,'distribution':15,'competition':10,'execution':5,'timing':5}
PROFILES={
'general': {'weights': BASE, 'pilot_gates': [],'questions':[]},
'bootstrapped_saas':{'weights':{'problem':20,'market':8,'value':15,'economics':22,'distribution':20,'competition':7,'execution':5,'timing':3},
 'pilot_gates':['pricing_test','delivery_margin','repeatable_channel'], 'questions':['Can a reachable niche pay enough to cover support and acquisition?','Is retention or repeat willingness observable?']},
'venture_startup':{'weights':{'problem':18,'market':21,'value':14,'economics':9,'distribution':13,'competition':9,'execution':5,'timing':11},
 'pilot_gates':['venture_scale_market','credible_growth_channel','funding_runway'], 'questions':['Is a sufficiently large accessible market evidenced?','Can growth and capital intensity support venture ambitions?']},
'marketplace':{'weights':{'problem':16,'market':15,'value':13,'economics':15,'distribution':20,'competition':10,'execution':7,'timing':4},
 'pilot_gates':['supply_commitments','demand_commitments','liquidity_model','transaction_margin'], 'questions':['How do both sides acquire liquidity at usable density?','What are incentives and disintermediation risks?']},
'services':{'weights':{'problem':20,'market':8,'value':18,'economics':20,'distribution':17,'competition':8,'execution':7,'timing':2},
 'pilot_gates':['paid_engagement','delivery_capacity','owner_dependence'], 'questions':['Can delivery scale beyond founder hours?','Can a repeatable scope and profit margin be demonstrated?']},
'regulated':{'weights':{'problem':13,'market':10,'value':10,'economics':15,'distribution':10,'competition':6,'execution':25,'timing':11},
 'pilot_gates':['jurisdiction_review','compliance_path','data_and_safety','professional_review'], 'questions':['Which permissions, licenses or reviews are mandatory?','What are clinical/legal/safety failure consequences?']}
}
assert all(sum(p['weights'].values())==100 for p in PROFILES.values())

USE_WHEN = {
    'general': 'You are unsure of the model, or none of the others fit; default weights, no extra gates.',
    'bootstrapped_saas': 'A small team will fund the product from revenue; margin, price and a repeatable channel decide.',
    'venture_startup': 'Investors must see a very large market and fast growth; scale and timing outweigh early margin.',
    'marketplace': 'Value depends on connecting two sides; supply, demand and liquidity decide.',
    'services': 'You sell your own or a team\'s hours or a productized service; paid demand and delivery capacity decide.',
    'regulated': 'Law, licensing or safety (health, finance, legal, children) can stop you; compliance and execution decide.',
}
# gate id -> (what it asks, an example evidence id that would satisfy it)
GATE_HELP = {
    'pricing_test': ('Real buyers were shown a price and some agreed to pay it.', 'ev-pricing-test-3-of-10-accepted'),
    'delivery_margin': ('Cost to deliver one unit is measured and leaves a margin at the tested price.', 'ev-delivery-cost-sheet'),
    'repeatable_channel': ('One acquisition channel produced customers more than once at a known cost.', 'ev-channel-cohort-2'),
    'venture_scale_market': ('The reachable market is large enough to return a fund, built bottom-up from sourced counts.', 'ev-bottom-up-sam'),
    'credible_growth_channel': ('A channel that scales without proportional headcount has early evidence.', 'ev-channel-growth-trial'),
    'funding_runway': ('The capital needed to reach the next milestone is estimated and a path to raise it exists.', 'ev-runway-model'),
    'supply_commitments': ('Suppliers committed (signed, listed or paid) before the product exists.', 'ev-supplier-commitments'),
    'demand_commitments': ('Buyers committed (deposit, pre-order or signed intent) before the product exists.', 'ev-buyer-deposits'),
    'liquidity_model': ('There is a plan and a number for matches per listing in one dense niche.', 'ev-liquidity-model'),
    'transaction_margin': ('Take rate minus payment, support and fraud cost is positive per transaction.', 'ev-take-rate-model'),
    'paid_engagement': ('At least one customer paid for the work at the intended price.', 'ev-paid-invoice'),
    'delivery_capacity': ('Hours per engagement are measured, and the number of clients the team can serve is known.', 'ev-hours-log'),
    'owner_dependence': ('The work can be delivered or sold without the founder in every engagement.', 'ev-sop-handoff'),
    'jurisdiction_review': ('The rules in the first target jurisdiction were read from the regulator and summarized.', 'ev-regulator-source'),
    'compliance_path': ('A named license, approval or registration path exists, with cost and time.', 'ev-compliance-plan'),
    'data_and_safety': ('Data handling and the worst safety failure are identified, with a control for each.', 'ev-safety-review'),
    'professional_review': ('A qualified professional (lawyer, clinician, compliance lead) reviewed the plan.', 'ev-professional-memo'),
}


def describe(name):
    """Everything `profiles show` prints, JSON-ready. Raises KeyError for an unknown profile."""
    p = PROFILES[name]
    return {'name': name, 'use_when': USE_WHEN[name], 'weights': dict(p['weights']), 'questions': list(p['questions']),
            'pilot_gates': [{'id': g, 'description': GATE_HELP[g][0], 'evidence_example': GATE_HELP[g][1]} for g in p['pilot_gates']]}


def summary():
    return [{'name': n, 'use_when': USE_WHEN[n], 'top_weights': top_weights(n), 'gates': len(p['pilot_gates'])} for n, p in PROFILES.items()]


def top_weights(name, n=3):
    w = PROFILES[name]['weights']
    return [{'pillar': k, 'weight': w[k]} for k in sorted(w, key=lambda k: (-w[k], k))[:n]]


def compare(a, b):
    """Per-pillar weights for two profiles with the difference (b minus a)."""
    wa, wb = PROFILES[a]['weights'], PROFILES[b]['weights']
    return {'a': a, 'b': b, 'rows': [{'pillar': k, 'a': wa[k], 'b': wb[k], 'diff': wb[k] - wa[k]} for k in wa],
            'gates_a': PROFILES[a]['pilot_gates'], 'gates_b': PROFILES[b]['pilot_gates']}


def _text(data, args):
    if 'rows' in data:
        out = [f"{'pillar':14}{data['a']:>20}{data['b']:>20}{'diff':>7}"]
        out += [f"{r['pillar']:14}{r['a']:>20}{r['b']:>20}{r['diff']:>+7}" for r in data['rows']]
        return "\n".join(out + [f"gates {data['a']}: {', '.join(data['gates_a']) or 'none'}", f"gates {data['b']}: {', '.join(data['gates_b']) or 'none'}"]) + "\n"
    if 'weights' in data:
        out = [data['name'], "  " + data['use_when'], "Weights:"]
        out += [f"  {k:13}{v:>3}" for k, v in sorted(data['weights'].items(), key=lambda kv: (-kv[1], kv[0]))]
        out.append("Pilot gates:" if data['pilot_gates'] else "Pilot gates: none")
        out += [f"  {g['id']}: {g['description']}\n      evidence such as: {g['evidence_example']}" for g in data['pilot_gates']]
        return "\n".join(out + (["Guiding questions:"] + ["  " + q for q in data['questions']] if data['questions'] else [])) + "\n"
    rows = [f"{r['name']:19}{r['gates']:>2} gates  {', '.join(t['pillar'] + ' ' + str(t['weight']) for t in r['top_weights'])}\n{'':19}{r['use_when']}" for r in data['profiles']]
    return "\n".join(rows) + "\n\nSee one: greenfield profiles show <name>; compare: greenfield profiles compare <a> <b>\n"


def _handler(args):
    from gf_common import GFError
    cmd = getattr(args, 'profiles_command', None)
    for n in (getattr(args, 'name', None), getattr(args, 'a', None), getattr(args, 'b', None)):
        if n is not None and n not in PROFILES:
            raise GFError(f"unknown profile {n!r}", hint="greenfield profiles   (lists: " + ", ".join(PROFILES) + ")")
    if cmd == 'show':
        return describe(args.name)
    if cmd == 'compare':
        return compare(args.a, args.b)
    return {'profiles': summary()}


def register(sub, cmd):
    """Add `profiles` (list), `profiles show NAME` and `profiles compare A B` to the CLI; cmd is cli._cmd."""
    p = cmd(sub, 'profiles', 'list the business-model profiles; show or compare them', [
        'greenfield profiles', 'greenfield profiles show marketplace', 'greenfield profiles compare bootstrapped_saas venture_startup'], _handler, _text)
    s = p.add_subparsers(dest='profiles_command', metavar='<command>')
    for name, help, names in (('show', 'weights, pilot gates and guiding questions of one profile', ['name']),
                              ('compare', 'weights of two profiles side by side', ['a', 'b'])):
        q = cmd(s, name, help, [f"greenfield profiles {name} " + " ".join(PROFILES_EX[:len(names)])], _handler, _text)
        for n in names:
            q.add_argument(n, help='profile name: ' + ', '.join(PROFILES))


PROFILES_EX = ['marketplace', 'services']
assert all(g in GATE_HELP for p in PROFILES.values() for g in p['pilot_gates']) and set(USE_WHEN) == set(PROFILES)
