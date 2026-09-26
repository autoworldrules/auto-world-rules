def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Prioritize facts that generate more entailed facts (longer reasoning chains).
    num_entailed = len(entailed_facts.strip().split('\n')) if entailed_facts.strip() else 0
    return float(num_entailed)
