def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # Prefer candidates that produce more entailed facts (more complex stories).
    num_entailed = len(entailed_facts.strip().split('\n')) if entailed_facts.strip() else 0
    return float(num_entailed)
