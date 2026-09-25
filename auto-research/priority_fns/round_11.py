def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    import re

    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    if fact_pred == 'not_living_in':
        return -100.0

    cand_args = re.findall(r'\d+', cand_fact)
    if len(cand_args) == 2 and cand_args[0] == cand_args[1]:
        return -1.0

    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Classify entailed facts by difficulty
    constraint_preds = {'no_brothers', 'no_sisters', 'no_sons', 'no_daughters',
                        'no_siblings', 'no_children'}
    maternal_paternal = {'maternal_grandparent_of', 'paternal_grandparent_of',
                         'maternal_grandmother_of', 'paternal_grandmother_of',
                         'maternal_grandfather_of', 'paternal_grandfather_of',
                         'maternal_aunt_of', 'paternal_aunt_of',
                         'maternal_uncle_of', 'paternal_uncle_of',
                         'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of'}
    multi_hop = {'grandparent_of', 'grandchild_of', 'grandmother_of', 'grandfather_of',
                 'grandson_of', 'granddaughter_of', 'aunt_of', 'uncle_of', 'aunt_or_uncle_of',
                 'nibling_of', 'nephew_of', 'niece_of', 'sibling_in_law_of',
                 'brother_in_law_of', 'sister_in_law_of', 'parent_in_law_of',
                 'father_in_law_of', 'mother_in_law_of', 'child_in_law_of',
                 'son_in_law_of', 'daughter_in_law_of'}

    preds = set()
    constraint_count = 0
    mat_pat_count = 0
    mh_count = 0
    unique_pairs = set()

    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            if pred in constraint_preds:
                constraint_count += 1
            if pred in maternal_paternal:
                mat_pat_count += 1
            if pred in multi_hop:
                mh_count += 1
            args = re.findall(r'\d+', line)
            if len(args) >= 2 and args[0] != args[1]:
                unique_pairs.add((args[0], args[1]))

    if fact_pred in ('living_in', 'living_in_same_place', 'is_person', 'is_place'):
        return float(num_entailed) * 0.1

    # Maternal/paternal distinctions are the hardest - require constraint reasoning
    # Weight: mat_pat > multi_hop > constraints > diversity > count
    return (float(num_entailed) +
            3.0 * len(preds) +
            5.0 * mh_count +
            10.0 * mat_pat_count +
            3.0 * constraint_count +
            2.0 * len(unique_pairs))
