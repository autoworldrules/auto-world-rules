def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    lines = entailed_facts.strip().split('\n')

    # Parse existing entity pairs from the story
    existing_pairs = {}
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            args = line.split('(')[1].rstrip(')').split(',')
            if len(args) == 2:
                pair = (args[0].strip(), args[1].strip())
                existing_pairs.setdefault(pair, set()).add(rel)

    # Score entailed facts: prefer those that ADD relations to existing pairs
    score = 0.0
    entailed_rels = set()
    overlap_count = 0
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            args = line.split('(')[1].rstrip(')').split(',')
            if len(args) == 2:
                pair = (args[0].strip(), args[1].strip())
                if pair in existing_pairs:
                    overlap_count += 1  # adds complexity to existing pairs

    # Prefer: many entailed, many overlapping pairs, diverse relations
    score = float(len(lines)) + overlap_count * 5.0 + len(entailed_rels) * 3.0
    return score
