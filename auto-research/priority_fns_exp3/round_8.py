def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    spatial = {'living_in', 'living_in_same_place'}
    lines = entailed_facts.strip().split('\n')

    existing_rels = set()
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            existing_rels.add(line.split('(')[0])

    score = 0.0
    entailed_rels = set()
    entailed_pairs = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            args_str = line.split('(')[1].rstrip(')')
            args = args_str.split(',')
            if len(args) == 2:
                entailed_pairs.add((args[0].strip(), args[1].strip()))
            if rel in spatial:
                score -= 1.0
            else:
                score += 3.0

    if cand_rel in spatial:
        score -= 3.0

    # Novel relations bonus (from round 5)
    novel_rels = entailed_rels - existing_rels - spatial
    score += len(novel_rels) * 10.0

    # Diversity bonus
    non_spatial = entailed_rels - spatial
    score += len(non_spatial) * 5.0

    # NEW: bonus for many unique entity pairs in entailments
    # More pairs = more potential queries = harder eval
    score += len(entailed_pairs) * 2.0

    return score
