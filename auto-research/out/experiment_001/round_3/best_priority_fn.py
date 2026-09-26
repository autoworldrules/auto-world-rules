def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Prioritize facts that generate more entailed facts AND involve family relationships.
    num_entailed = len(entailed_facts.strip().split('\n')) if entailed_facts.strip() else 0

    # Bonus for family relationship facts (not simple location/gender/property facts)
    simple_preds = ['living_in', 'living_in_same_place', 'is_male', 'is_female',
                    'is_underage', 'is_person', 'is_place']
    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')

    bonus = 0.0
    if fact_pred not in simple_preds:
        bonus = 5.0  # Boost family relationship facts

    return float(num_entailed) + bonus
