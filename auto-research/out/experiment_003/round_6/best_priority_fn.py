def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0

    spatial = {'living_in', 'living_in_same_place'}
    deep_family = {'grandparent_of', 'grandchild_of', 'grandmother_of', 'grandfather_of',
                   'granddaughter_of', 'grandson_of', 'parent_in_law_of', 'child_in_law_of',
                   'sibling_in_law_of', 'sister_in_law_of', 'brother_in_law_of',
                   'aunt_or_uncle_of', 'nibling_of', 'aunt_of', 'uncle_of',
                   'niece_of', 'nephew_of'}
    # Skip candidates with "not_" prefix (negated facts cause vocab issues)
    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    lines = entailed_facts.strip().split('\n')
    existing_rels = set()
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            existing_rels.add(line.split('(')[0])

    score = 0.0
    entailed_rels = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            if rel in spatial:
                score -= 1.0
            elif rel in deep_family:
                score += 8.0
            else:
                score += 3.0

    if cand_rel in spatial:
        score -= 3.0

    novel_rels = entailed_rels - existing_rels - spatial
    score += len(novel_rels) * 10.0
    non_spatial = entailed_rels - spatial
    score += len(non_spatial) * 5.0
    return score
