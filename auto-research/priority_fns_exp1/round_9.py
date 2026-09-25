def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    import re

    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    if fact_pred == 'not_living_in':
        return -100.0

    # Strongly prefer binary relationship facts over unary properties
    cand_args = re.findall(r'\d+', cand_fact)
    if len(cand_args) == 2 and cand_args[0] == cand_args[1]:
        return -1.0  # Penalize self-referential facts

    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    multi_hop_preds = {'grandparent_of', 'grandchild_of', 'grandmother_of', 'grandfather_of',
                       'grandson_of', 'granddaughter_of', 'aunt_of', 'uncle_of', 'aunt_or_uncle_of',
                       'nibling_of', 'nephew_of', 'niece_of', 'sibling_in_law_of',
                       'brother_in_law_of', 'sister_in_law_of', 'parent_in_law_of',
                       'father_in_law_of', 'mother_in_law_of', 'child_in_law_of',
                       'son_in_law_of', 'daughter_in_law_of',
                       'maternal_grandparent_of', 'paternal_grandparent_of',
                       'maternal_grandmother_of', 'paternal_grandmother_of',
                       'maternal_grandfather_of', 'paternal_grandfather_of',
                       'maternal_aunt_of', 'paternal_aunt_of',
                       'maternal_uncle_of', 'paternal_uncle_of',
                       'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of'}

    preds = set()
    multi_hop_count = 0
    unique_entity_pairs = set()
    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            if pred in multi_hop_preds:
                multi_hop_count += 1
            args = re.findall(r'\d+', line)
            if len(args) >= 2 and args[0] != args[1]:
                unique_entity_pairs.add((args[0], args[1]))

    # Penalize location facts but keep gender/constraint facts with small bonus
    if fact_pred in ('living_in', 'living_in_same_place', 'is_person', 'is_place'):
        return float(num_entailed) * 0.1
    if fact_pred in ('is_male', 'is_female', 'is_underage'):
        return float(num_entailed) * 0.5 + multi_hop_count  # Gender can trigger multi-hop

    # Core family relationships get full bonus
    return float(num_entailed) + 3.0 * len(preds) + 7.0 * multi_hop_count + 2.0 * len(unique_entity_pairs)
