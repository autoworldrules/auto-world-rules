def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    import re

    fact_pred = cand_fact.split('(')[0] if '(' in cand_fact else cand_fact.rstrip('.')
    if fact_pred == 'not_living_in':
        return -100.0

    cand_args = re.findall(r'\d+', cand_fact)
    if len(cand_args) == 2 and cand_args[0] == cand_args[1]:
        return -1.0

    if not entailed_facts.strip():
        return 0.0

    lines = entailed_facts.strip().split('\n')
    num_entailed = len(lines)

    # Build simple adjacency from existing facts to find disconnected components
    existing_lines = facts_program.strip().split('\n') if facts_program.strip() else []
    adj = {}
    existing_preds = set()
    for el in existing_lines:
        args = re.findall(r'\d+', el)
        if '(' in el:
            existing_preds.add(el.strip().split('(')[0])
        if len(args) >= 2 and args[0] != args[1]:
            adj.setdefault(args[0], set()).add(args[1])
            adj.setdefault(args[1], set()).add(args[0])

    # Check if candidate bridges two components (entities not yet connected)
    bridge_bonus = 0.0
    if len(cand_args) >= 2 and cand_args[0] != cand_args[1]:
        # BFS from arg0 to see if arg1 is reachable
        visited = set()
        queue = [cand_args[0]]
        visited.add(cand_args[0])
        while queue:
            node = queue.pop(0)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        if cand_args[1] not in visited:
            bridge_bonus = 20.0  # Massive bonus for bridging

    maternal_paternal = {'maternal_grandparent_of', 'paternal_grandparent_of',
                         'maternal_grandmother_of', 'paternal_grandmother_of',
                         'maternal_grandfather_of', 'paternal_grandfather_of',
                         'maternal_aunt_of', 'paternal_aunt_of',
                         'maternal_uncle_of', 'paternal_uncle_of',
                         'maternal_aunt_or_uncle_of', 'paternal_aunt_or_uncle_of'}
    multi_hop = {'grandparent_of', 'grandchild_of', 'grandmother_of', 'grandfather_of',
                 'grandson_of', 'granddaughter_of', 'aunt_of', 'uncle_of', 'aunt_or_uncle_of',
                 'nibling_of', 'nephew_of', 'niece_of', 'sibling_in_law_of',
                 'brother_in_law_of', 'sister_in_law_of', 'parent_in_law_of',
                 'father_in_law_of', 'mother_in_law_of', 'child_in_law_of',
                 'son_in_law_of', 'daughter_in_law_of'}

    preds = set()
    mat_pat_count = 0
    mh_count = 0
    # Count NEW predicates not seen in existing facts
    new_pred_count = 0

    for line in lines:
        line = line.strip()
        if '(' in line:
            pred = line.split('(')[0]
            preds.add(pred)
            if pred not in existing_preds:
                new_pred_count += 1
            if pred in maternal_paternal:
                mat_pat_count += 1
            elif pred in multi_hop:
                mh_count += 1

    if fact_pred in ('living_in', 'living_in_same_place', 'is_person', 'is_place'):
        return float(num_entailed) * 0.1 + bridge_bonus * 0.5

    return (float(num_entailed) +
            3.0 * len(preds) +
            5.0 * mh_count +
            12.0 * mat_pat_count +
            2.0 * new_pred_count +
            bridge_bonus)
