def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0
    lines = entailed_facts.strip().split('\n')

    spatial = {'living_in', 'living_in_same_place'}

    # Count existing relations in story
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
            entailed_rels.add(rel)
            if rel in spatial:
                score -= 1.0  # actively penalize spatial
            else:
                score += 3.0

    # Big bonus for NEW relation types not already in the story
    novel_rels = entailed_rels - existing_rels - spatial
    score += len(novel_rels) * 10.0

    # Bonus for total diversity
    non_spatial = entailed_rels - spatial
    score += len(non_spatial) * 5.0
    return score
