import json
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
PAID = ('paid_test', 'signed_commitment', 'repeat_purchase')
FP = ('feasibility_proof',)
FP_PT = ('feasibility_proof', 'paid_test')
FP_C = ('feasibility_proof', 'claim')
CH = ('customer_action', 'paid_test', 'repeat_purchase')
COMMIT = ('signed_commitment', 'paid_test')
LIQ = ('feasibility_proof', 'customer_action', 'repeat_purchase')
RUN = ('feasibility_proof', 'signed_commitment')
# gate id -> what it asks, an example of what satisfies it, and the ledger kinds (or 'claim') it accepts
GATE_HELP = {
    'pricing_test': {'description': 'Real buyers were shown a price and some agreed to pay it.', 'example': 'presale export', 'accepts': PAID},
    'delivery_margin': {'description': 'Cost to deliver one unit is measured and leaves a margin at the tested price.', 'example': 'delivery cost model', 'accepts': FP},
    'repeatable_channel': {'description': 'One acquisition channel produced customers more than once at a known cost.', 'example': 'repeat cohort export', 'accepts': CH},
    'venture_scale_market': {'description': 'The reachable market is large enough to return a fund, built bottom-up from sourced counts.', 'example': 'market size model, or a reviewed sourced count', 'accepts': FP_C},
    'credible_growth_channel': {'description': 'A channel that scales without proportional headcount has early evidence.', 'example': 'channel analytics export', 'accepts': CH},
    'funding_runway': {'description': 'The capital needed to reach the next milestone is estimated and a path to raise it exists.', 'example': 'runway model', 'accepts': RUN},
    'supply_commitments': {'description': 'Suppliers committed (signed, listed or paid) before the product exists.', 'example': 'supplier LOIs', 'accepts': COMMIT},
    'demand_commitments': {'description': 'Buyers committed (deposit, pre-order or signed intent) before the product exists.', 'example': 'buyer deposits', 'accepts': COMMIT},
    'liquidity_model': {'description': 'There is a plan and a number for matches per listing in one dense niche.', 'example': 'liquidity model', 'accepts': LIQ},
    'transaction_margin': {'description': 'Take rate minus payment, support and fraud cost is positive per transaction.', 'example': 'take-rate model or paid invoice', 'accepts': FP_PT},
    'paid_engagement': {'description': 'At least one customer paid for the work at the intended price.', 'example': 'paid invoice', 'accepts': PAID},
    'delivery_capacity': {'description': 'Hours per engagement are measured, and the number of clients the team can serve is known.', 'example': 'hours log', 'accepts': FP},
    'owner_dependence': {'description': 'The work can be delivered or sold without the founder in every engagement.', 'example': 'handoff ops record', 'accepts': FP},
    'jurisdiction_review': {'description': 'The rules in the first target jurisdiction were read from the regulator and summarized.', 'example': 'reviewed regulator claim, or counsel memo', 'accepts': FP_C},
    'compliance_path': {'description': 'A named license, approval or registration path exists, with cost and time.', 'example': 'compliance plan memo', 'accepts': FP},
    'data_and_safety': {'description': 'Data handling and the worst safety failure are identified, with a control for each.', 'example': 'safety review memo', 'accepts': FP},
    'professional_review': {'description': 'A qualified professional (lawyer, clinician, compliance lead) reviewed the plan.', 'example': 'signed professional memo', 'accepts': FP},
}


def describe(name):
    """Everything `profiles show` prints, JSON-ready. Raises KeyError for an unknown profile."""
    p = PROFILES[name]
    return {'name': name, 'use_when': USE_WHEN[name], 'weights': dict(p['weights']), 'questions': list(p['questions']),
            'pilot_gates': [{'id': g, 'description': GATE_HELP[g]['description'], 'evidence_example': GATE_HELP[g]['example']} for g in p['pilot_gates']],
            'pilot_gates_skeleton': {g: {'passed': False, 'evidence_ids': []} for g in p['pilot_gates']}}


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
        out.append("Paste into evaluation.json:\n  " + ('"pilot_gates": ' + json.dumps(data['pilot_gates_skeleton']) if data['pilot_gates_skeleton'] else "{} (no gates)"))
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
