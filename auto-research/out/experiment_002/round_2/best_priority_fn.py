def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    # From exp1: entailed facts count was the biggest single-round improvement.
    num_entailed = len(entailed_facts.strip().split('\n')) if entailed_facts.strip() else 0
    return float(num_entailed)
