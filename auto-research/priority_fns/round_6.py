def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Combine entailed diversity with entity connectivity density.
    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Count unique predicates in entailed facts
    preds = set()
    for line in lines:
        line = line.strip()
        if '(' in line:
            preds.add(line.split('(')[0])

    # Count how many existing facts mention the same entities as the candidate
    # Dense connectivity = harder to predict
    import re
    cand_args = re.findall(r'\d+', cand_fact)

    existing_lines = facts_program.strip().split('\n') if facts_program.strip() else []
    connectivity = 0
    for el in existing_lines:
        for arg in cand_args:
            if arg in re.findall(r'\d+', el):
                connectivity += 1
                break

    # Simple penalty
    simple_preds = {'living_in', 'living_in_same_place', 'is_person', 'is_place'}
    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    family_bonus = 5.0 if fact_pred not in simple_preds else 0.0

    return float(num_entailed) + 3.0 * len(preds) + 0.5 * connectivity + family_bonus
