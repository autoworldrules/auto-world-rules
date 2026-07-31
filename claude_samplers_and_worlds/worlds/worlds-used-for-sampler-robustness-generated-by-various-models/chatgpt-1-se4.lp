% =========================
% Domain Base Facts
% =========================

person(alice).
person(bob).
person(carol).
person(david).
person(eve).
person(frank).
person(grace).
person(henry).

task(t1).
task(t2).
task(t3).
task(t4).

skill(s1).
skill(s2).
skill(s3).
skill(s4).

has_skill(alice,s1).
has_skill(bob,s2).
has_skill(carol,s1).
has_skill(carol,s3).
has_skill(david,s2).
has_skill(eve,s3).
has_skill(frank,s4).
has_skill(grace,s1).
has_skill(henry,s4).

requires(t1,s1).
requires(t2,s2).
requires(t3,s3).
requires(t4,s4).

depends(t2,t1).
depends(t3,t2).
depends(t4,t3).

collaborates(alice,bob).
collaborates(bob,carol).
collaborates(carol,david).
collaborates(david,eve).
collaborates(eve,frank).
collaborates(frank,grace).
collaborates(grace,henry).

% =========================
% Rule Base
% =========================

% Assignment possibilities
{assigned(P,T),not_assigned(P,T)} :- person(P), task(T).

% Skill-based assignment
qualified(P,T) :- has_skill(P,S), requires(T,S).
assigned(P,T) :- qualified(P,T), not blocked(P,T).

% Blocking conditions
blocked(P,T) :- depends(T,T2), not assigned(P,T2).
blocked(P,T) :- conflict(P,T).

% Conflict propagation
conflict(P,T) :- assigned(P,T2), depends(T,T2).
conflict(P,T) :- collaborates(P,Q), assigned(Q,T).

% Dependency propagation
depends(T1,T3) :- depends(T1,T2), depends(T2,T3).

% Collaboration symmetry
collaborates(X,Y) :- collaborates(Y,X).

% Indirect collaboration
indirect_collab(X,Z) :- collaborates(X,Y), collaborates(Y,Z).

% Influence rules
influences(X,Z) :- indirect_collab(X,Z).
influences(X,Z) :- collaborates(X,Z).

% Skill sharing through influence
shared_skill(X,S) :- influences(X,Y), has_skill(Y,S).

% Derived qualification
qualified(P,T) :- shared_skill(P,S), requires(T,S).

% Mutual exclusion of assignment
:- assigned(P,T), not_assigned(P,T).

% Task must be assigned if possible
must_assign(T) :- requires(T,S).
assigned(P,T) :- must_assign(T), qualified(P,T), not conflict(P,T).

% No duplicate assignments
:- assigned(P,T), assigned(Q,T), P != Q.

% Propagation of blocking
blocked(P,T) :- blocked(P,T2), depends(T,T2).

% Chain influence
chain_influence(X,Z) :- influences(X,Y), influences(Y,Z).

% Extended skill sharing
shared_skill(X,S) :- chain_influence(X,Y), has_skill(Y,S).

% Task chaining
task_chain(T1,T3) :- depends(T1,T2), depends(T2,T3).

% Assignment via chain
assigned(P,T) :- task_chain(T,T2), assigned(P,T2), not blocked(P,T).

% Reverse dependency conflict
conflict(P,T) :- assigned(P,T2), depends(T2,T).

% Isolation rule
isolated(P) :- person(P), not collaborates(P,_).

% Isolated cannot share skills
:- isolated(P), shared_skill(P,S).

% Enforce at least one assignment per person
{active(P)} :- person(P).
active(P) :- assigned(P,T).

% Prevent idle contradictions
:- active(P), not assigned(P,_).

% Skill dominance
dominates(P,Q) :- has_skill(P,S), not has_skill(Q,S).

% Dominance-based assignment
assigned(P,T) :- dominates(P,Q), assigned(Q,T), not conflict(P,T).

% Prevent circular dominance
:- dominates(P,Q), dominates(Q,P).

% Task exclusivity via collaboration
:- assigned(P,T), assigned(Q,T), collaborates(P,Q).

% Collaborative assignment propagation
assigned(Q,T) :- assigned(P,T), collaborates(P,Q), not conflict(Q,T).

% Prevent over-propagation
:- assigned(P,T), assigned(P,T2), depends(T,T2).

% Skill inheritance restriction
:- shared_skill(P,S), has_skill(P,S).

% Derived blocking from influence
blocked(P,T) :- influences(P,Q), conflict(Q,T).

% Ensure dependency satisfaction
:- assigned(P,T), depends(T,T2), not assigned(P,T2).

% Transitive conflict
conflict(P,T3) :- conflict(P,T2), depends(T3,T2).

% Mutual influence constraint
:- influences(P,Q), influences(Q,P), P != Q.

% Assign only if not isolated
:- assigned(P,T), isolated(P).

% Skill propagation constraint
:- shared_skill(P,S), not has_skill(P,S), not influences(P,_).

% Final consistency constraint
:- assigned(P,T), blocked(P,T).

