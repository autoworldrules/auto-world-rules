def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    spatial = {'living_in', 'living_in_same_place'}
    # These "seed" relations trigger deep entailment chains
    seed_rels = {'father_of', 'mother_of', 'son_of', 'daughter_of',
                 'husband_of', 'wife_of', 'brother_of', 'sister_of'}

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
            else:
                score += 3.0

    # Strong bonus if the candidate itself is a seed relation
    if cand_rel in seed_rels:
        score += 20.0

    # Penalize spatial candidates
    if cand_rel in spatial:
        score -= 5.0

    # Novel relations bonus
    novel_rels = entailed_rels - existing_rels - spatial
    score += len(novel_rels) * 10.0

    non_spatial = entailed_rels - spatial
    score += len(non_spatial) * 5.0
    return score
