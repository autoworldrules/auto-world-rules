def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return -10.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    trivial = {'living_in', 'living_in_same_place', 'is_person', 'is_place',
               'is_male', 'is_female', 'is_underage', 'no_brothers', 'no_sisters',
               'no_sons', 'no_daughters'}

    # Multi-hop: require 2+ rule applications
    multi_hop = {'grandmother_of', 'grandfather_of', 'granddaughter_of', 'grandson_of',
                 'maternal_grandmother_of', 'maternal_grandfather_of',
                 'paternal_grandmother_of', 'paternal_grandfather_of',
                 'aunt_of', 'uncle_of', 'niece_of', 'nephew_of',
                 'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of',
                 'maternal_uncle_of', 'paternal_uncle_of',
                 'great_grandparent_of', 'great_grandchild_of',
                 'sister_in_law_of', 'brother_in_law_of',
                 'father_in_law_of', 'mother_in_law_of',
                 'son_in_law_of', 'daughter_in_law_of'}

    # Single-hop derived (still hard but less than multi-hop)
    single_hop = {'parent_of', 'child_of', 'grandparent_of', 'grandchild_of',
                  'sibling_of', 'spouse_of', 'sibling_in_law_of',
                  'parent_in_law_of', 'child_in_law_of',
                  'aunt_or_uncle_of', 'nibling_of'}

    lines = entailed_facts.strip().split('\n')

    existing_rels = set()
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            existing_rels.add(line.split('(')[0])

    score = 0.0
    entailed_rels = set()
    multi_hop_count = 0
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            if rel in trivial:
                score -= 1.0
            elif rel in multi_hop:
                score += 15.0
                multi_hop_count += 1
            elif rel in single_hop:
                score += 5.0
            else:
                score += 2.0

    novel_rels = entailed_rels - existing_rels - trivial
    score += len(novel_rels) * 10.0
    non_trivial = entailed_rels - trivial
    score += len(non_trivial) * 5.0

    # Extra bonus for having many multi-hop entailments
    score += multi_hop_count * 5.0

    return score
