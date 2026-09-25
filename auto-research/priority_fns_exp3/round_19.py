def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Round 15's approach was best. This is a slight refinement:
    # add a bonus for candidates that connect entities with many existing relations
    # (creating denser, more confusing graphs)
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

    existing_rels = set()
    entity_degree = {}
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            existing_rels.add(rel)
            args = line.split('(')[1].rstrip(')').split(',')
            for a in args:
                a = a.strip()
                entity_degree[a] = entity_degree.get(a, 0) + 1

    # Check candidate entity connectivity
    cand_connectivity = 0.0
    if '(' in cand_fact:
        args = cand_fact.strip().rstrip('.').split('(')[1].rstrip(')').split(',')
        for a in args:
            a = a.strip()
            cand_connectivity += entity_degree.get(a, 0)

    score = 0.0
    entailed_rels = set()
    multi_hop_count = 0
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            if rel in trivial:
                score -= 2.0
            elif rel in multi_hop:
                score += 20.0
                multi_hop_count += 1
            else:
                score += 1.0

    novel_rels = entailed_rels - existing_rels - trivial
    score += len(novel_rels) * 10.0
    non_trivial = entailed_rels - trivial
    score += len(non_trivial) * 3.0
    score += multi_hop_count * 8.0

    # Small bonus for connecting well-connected entities (denser graphs)
    score += cand_connectivity * 0.5

    return score
