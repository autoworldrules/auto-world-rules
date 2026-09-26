def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return -10.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    spatial = {'living_in', 'living_in_same_place', 'is_person', 'is_place',
               'is_male', 'is_female', 'is_underage', 'no_brothers', 'no_sisters',
               'no_sons', 'no_daughters'}

    lines = entailed_facts.strip().split('\n')
    family_count = 0
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel not in spatial and not rel.startswith('not_'):
                family_count += 1

    # Pure signal: count of non-trivial entailed facts
    return float(family_count)
