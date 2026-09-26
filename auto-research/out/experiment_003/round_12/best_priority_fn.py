def priority(cand_fact: str, definite_rules_program: str, entailed_facts: str, facts_program: str) -> float:
    if not entailed_facts.strip():
        return -10.0

    cand_rel = cand_fact.strip().rstrip('.').split('(')[0] if '(' in cand_fact else ''
    if cand_rel.startswith('not_'):
        return -100.0

    trivial = {'living_in', 'living_in_same_place', 'is_person', 'is_place',
               'is_male', 'is_female', 'is_underage', 'no_brothers', 'no_sisters',
               'no_sons', 'no_daughters'}

    lines = entailed_facts.strip().split('\n')

    # Parse the rules to find "deep" relations (those appearing in rule heads
    # that reference other derived relations in their body)
    rule_heads = set()
    rule_body_rels = {}
    for rule_line in definite_rules_program.strip().split('\n'):
        rule_line = rule_line.strip()
        if ':-' in rule_line:
            head = rule_line.split('(')[0].strip()
            rule_heads.add(head)
            body = rule_line.split(':-')[1]
            body_rels = set()
            for part in body.split('),'):
                part = part.strip().rstrip('.').rstrip(')')
                if '(' in part:
                    br = part.split('(')[0].strip().lstrip(',').strip()
                    body_rels.add(br)
            rule_body_rels[head] = body_rels

    # Relations that depend on other derived relations (multi-hop)
    derived = set()
    for head, body in rule_body_rels.items():
        if body & rule_heads:  # body contains another derived relation
            derived.add(head)

    existing_rels = set()
    for line in facts_program.strip().split('\n'):
        line = line.strip().rstrip('.')
        if '(' in line:
            existing_rels.add(line.split('(')[0])

    score = 0.0
    entailed_rels = set()
    for line in lines:
        line = line.strip().rstrip('.')
        if '(' in line:
            rel = line.split('(')[0]
            if rel.startswith('not_'):
                continue
            entailed_rels.add(rel)
            if rel in trivial:
                score -= 1.0
            elif rel in derived:
                score += 10.0  # multi-hop derived relations are hardest
            else:
                score += 3.0

    novel_rels = entailed_rels - existing_rels - trivial
    score += len(novel_rels) * 10.0
    non_trivial = entailed_rels - trivial
    score += len(non_trivial) * 5.0
    return score
