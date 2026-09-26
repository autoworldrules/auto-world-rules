def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return -10.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    trivial = {'living_in', 'living_in_same_place', 'is_person', 'is_place',
               'is_male', 'is_female', 'is_underage', 'no_brothers', 'no_sisters',
               'no_sons', 'no_daughters'}

    multi_hop = {'grandmother_of', 'grandfather_of', 'granddaughter_of', 'grandson_of',
                 'maternal_grandmother_of', 'maternal_grandfather_of',
                 'paternal_grandmother_of', 'paternal_grandfather_of',
                 'aunt_of', 'uncle_of', 'niece_of', 'nephew_of',
                 'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of',
                 'maternal_uncle_of', 'paternal_uncle_of',
                 'great_grandparent_of', 'great_grandchild_of',
                 'sister_in_law_of', 'brother_in_law_of',
                 'father_in_law_of', 'mother_in_law_of',
                 'son_in_law_of', 'daughter_in_law_of'}

    lines = entailed_facts.strip().split('\n')

    # Pure multi-hop count - ignore everything else
    multi_hop_count = 0
    multi_hop_rels = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel in multi_hop:
                multi_hop_count += 1
                multi_hop_rels.add(rel)

    # Penalize trivial candidates
    if cand_rel in trivial:
        return float(multi_hop_count) - 5.0

    # Pure signal: count of multi-hop entailments + diversity
    return float(multi_hop_count) + len(multi_hop_rels) * 3.0
