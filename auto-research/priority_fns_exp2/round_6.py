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

    # OPPOSITE emphasis from round 3: focus on in-law and sibling-in-law
    # (while round 3 focused on maternal/paternal)
    in_law = {'parent_in_law_of', 'father_in_law_of', 'mother_in_law_of',
              'child_in_law_of', 'son_in_law_of', 'daughter_in_law_of',
              'sibling_in_law_of', 'brother_in_law_of', 'sister_in_law_of'}
    # Still penalize location facts
    if fact_pred in ('living_in', 'living_in_same_place', 'is_person', 'is_place'):
        return float(num_entailed) * 0.1

    preds = set()
    in_law_count = 0
    pair_rels = {}
    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            if pred in in_law:
                in_law_count += 1
            args = re.findall(r'\d+', line)
            if len(args) >= 2 and args[0] != args[1]:
                pair_rels.setdefault((args[0], args[1]), set()).add(pred)

    dense_pairs = sum(1 for v in pair_rels.values() if len(v) >= 3)

    # Heavy in-law focus for conflicting patterns with round 3 data
    return (float(num_entailed) +
            3.0 * len(preds) +
            15.0 * in_law_count +
            7.0 * dense_pairs)
