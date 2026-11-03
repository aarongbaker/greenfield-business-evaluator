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
