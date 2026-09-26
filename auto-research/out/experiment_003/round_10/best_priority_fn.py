def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return 0.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    spatial = {'living_in', 'living_in_same_place'}
    lines = entailed_facts.strip().split('\n')

    # Count existing facts to determine story "phase"
    existing_facts = [l for l in facts_program.strip().split('\n') if l.strip()]
    num_existing = len(existing_facts)

    existing_rels = set()
    for line in existing_facts:
        line = line.strip().rstrip('.')
        if '(' in line:
            existing_rels.add(line.split('(')[0])

    entailed_rels = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if not rel.startswith('not_'):
                entailed_rels.add(rel)

    non_spatial = entailed_rels - spatial
    novel_rels = entailed_rels - existing_rels - spatial

    # Alternate strategy: early facts maximize diversity, later facts minimize it
    # This creates stories where initial structure is complex but later additions
    # create confusing/contradictory-looking patterns
    if num_existing < 12:
        # Early phase: maximize novel relations and entailments
        score = float(len(lines)) + len(novel_rels) * 15.0 + len(non_spatial) * 5.0
        if cand_rel in spatial:
            score -= 5.0
    else:
        # Late phase: prefer candidates that entail relations ALREADY in the story
        # (creates redundancy/confusion in the graph)
        overlap = entailed_rels & existing_rels - spatial
        score = len(overlap) * 10.0 + float(len(lines)) * 0.5
        if cand_rel in spatial:
            score -= 3.0

    return score
