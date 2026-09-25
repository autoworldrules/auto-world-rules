def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Maximize diversity of entailed fact predicates + total entailed count.
    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Count unique predicates in entailed facts
    preds = set()
    for line in lines:
        line = line.strip()
        if '(' in line:
            preds.add(line.split('(')[0])

    # Bonus for family relationship candidate facts
    simple_preds = {'living_in', 'living_in_same_place', 'is_male', 'is_female',
                    'is_underage', 'is_person', 'is_place'}
    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    family_bonus = 5.0 if fact_pred not in simple_preds else 0.0

    return float(num_entailed) + 3.0 * len(preds) + family_bonus
