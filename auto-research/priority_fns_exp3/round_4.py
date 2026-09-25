def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0
    lines = entailed_facts.strip().split('\n')

    # Categorize entailed relations
    spatial = {'living_in', 'living_in_same_place'}
    score = 0.0
    relations = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            relations.add(rel)
            if rel in spatial:
                score += 0.1  # low weight for easy spatial
            else:
                score += 3.0  # high weight for family/complex relations

    # Bonus for diversity of non-spatial relations
    non_spatial = relations - spatial
    score += len(non_spatial) * 5.0
    return score
