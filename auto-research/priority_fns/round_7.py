def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    import re

    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')

    # Reject problematic predicates
    if fact_pred == 'not_living_in':
        return -100.0

    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Unique entailed predicates
    preds = set()
    entailed_pairs = set()
    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            args = re.findall(r'\d+', line)
            if len(args) >= 2:
                entailed_pairs.add((args[0], args[1]))

    # Count how many entailed fact pairs already appear in existing facts
    existing_pairs = set()
    for el in (facts_program.strip().split('\n') if facts_program.strip() else []):
        args = re.findall(r'\d+', el)
        if len(args) >= 2:
            existing_pairs.add((args[0], args[1]))

    overlap = len(entailed_pairs & existing_pairs)

    # Entity connectivity
    cand_args = re.findall(r'\d+', cand_fact)
    existing_lines = facts_program.strip().split('\n') if facts_program.strip() else []
    connectivity = sum(1 for el in existing_lines if any(a in re.findall(r'\d+', el) for a in cand_args))

    # Penalize simple location facts
    if fact_pred in ('living_in', 'living_in_same_place', 'is_person', 'is_place'):
        return float(num_entailed) * 0.3

    return float(num_entailed) + 3.0 * len(preds) + 0.5 * connectivity + 4.0 * overlap
