def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Prefer candidates that produce diverse entailed relation types.
    if not entailed_facts.strip():
        return 0.0
    lines = entailed_facts.strip().split('\n')
    relations = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            relations.add(line.split('(')[0])
    # Combine count and diversity: diversity weighted more
    return float(len(relations)) * 2.0 + float(len(lines))
