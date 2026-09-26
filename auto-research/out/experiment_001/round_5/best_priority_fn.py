def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Maximize complex reasoning chains, especially gender-constraint derived ones.
    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Count unique predicates
    preds = set()
    complex_count = 0
    gender_constraint_count = 0
    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            # Count complex multi-step relationships
            if pred in ('grandmother_of', 'grandfather_of', 'grandparent_of', 'grandchild_of',
                        'grandson_of', 'granddaughter_of', 'aunt_of', 'uncle_of',
                        'aunt_or_uncle_of', 'nibling_of', 'nephew_of', 'niece_of',
                        'maternal_grandparent_of', 'paternal_grandparent_of',
                        'maternal_aunt_of', 'paternal_aunt_of',
                        'maternal_uncle_of', 'paternal_uncle_of',
                        'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of',
                        'son_in_law_of', 'daughter_in_law_of', 'child_in_law_of',
                        'parent_in_law_of', 'father_in_law_of', 'mother_in_law_of',
                        'sibling_in_law_of', 'brother_in_law_of', 'sister_in_law_of'):
                complex_count += 1
            if pred in ('no_brothers', 'no_sisters', 'no_sons', 'no_daughters',
                        'no_siblings', 'no_children'):
                gender_constraint_count += 1

    # Penalize candidate facts that are too simple
    simple_preds = {'living_in', 'living_in_same_place', 'is_person', 'is_place'}
    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    if fact_pred in simple_preds:
        return float(num_entailed) * 0.5

    return float(num_entailed) + 3.0 * len(preds) + 5.0 * complex_count + 3.0 * gender_constraint_count
