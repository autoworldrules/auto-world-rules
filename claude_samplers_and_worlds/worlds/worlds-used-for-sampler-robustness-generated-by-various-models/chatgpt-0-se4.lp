% ==========================================
% DOMAIN BASE FACTS
% ==========================================


researcher(alice).
researcher(bob).
researcher(carol).
researcher(dave).
researcher(eve).
researcher(frank).
researcher(grace).

institution(inst1).
institution(inst2).

field(ai).
field(logic).
field(networks).

affiliated(alice,inst1).
affiliated(bob,inst1).
affiliated(carol,inst2).
affiliated(dave,inst2).
affiliated(eve,inst1).
affiliated(frank,inst2).
affiliated(grace,inst1).

works_in(alice,ai).
works_in(bob,logic).
works_in(carol,ai).
works_in(dave,networks).
works_in(eve,logic).
works_in(frank,ai).
works_in(grace,networks).

collaborates(alice,bob).
collaborates(bob,carol).
collaborates(carol,dave).
collaborates(dave,eve).
collaborates(eve,frank).
collaborates(frank,grace).
collaborates(grace,alice).

cites(alice,carol).
cites(bob,alice).
cites(carol,frank).
cites(dave,bob).
cites(eve,carol).
cites(frank,alice).
cites(grace,dave).

% ==========================================
% Rule Base
% ==========================================

% Collaboration Symmetry & Propagation
collaborates(X,Y) :- collaborates(Y,X).
indirect_collab(X,Z) :- collaborates(X,Y), collaborates(Y,Z).
indirect_collab(X,Z) :- indirect_collab(X,Y), collaborates(Y,Z).

% Citation Influence
influences(X,Y) :- cites(Y,X).
influences(X,Z) :- influences(X,Y), influences(Y,Z).

% Field Interaction
same_field(X,Y) :- works_in(X,F), works_in(Y,F), X!=Y.
cross_field(X,Y) :- works_in(X,F), works_in(Y,G), F!=G.

% Institutional Dynamics
same_institution(X,Y) :- affiliated(X,I), affiliated(Y,I), X!=Y.
different_institution(X,Y) :- affiliated(X,I), affiliated(Y,J), I!=J.

% Authority and Expertise
expert(X,F) :- works_in(X,F), influences(X,Y).
recognized(X) :- expert(X,F), collaborates(Y,X).

% Collaboration vs Influence Tension
{ally(X,Y), rival(X,Y)} :- collaborates(X,Y).
:- ally(X,Y), rival(X,Y).

% Rivalry from Citation Loops
rival(X,Y) :- cites(X,Y), cites(Y,X).
rival(X,Y) :- influences(X,Y), influences(Y,X).

% Trust and Reputation
trusts(X,Y) :- ally(X,Y).
trusts(X,Y) :- influences(Y,X).
distrusts(X,Y) :- rival(X,Y).

% Propagation of Trust
trusts(X,Z) :- trusts(X,Y), trusts(Y,Z).

% Conflict Constraints
:- trusts(X,Y), distrusts(X,Y).

% Leadership Roles
leader(X) :- recognized(X), not follower(X).
follower(X) :- trusts(X,Y), influences(Y,X).

% Academic Lineage
mentor(X,Y) :- influences(X,Y), collaborates(X,Y).
mentee(Y,X) :- mentor(X,Y).
academic_ancestor(X,Z) :- mentor(X,Y), mentor(Y,Z).
academic_ancestor(X,Z) :- academic_ancestor(X,Y), mentor(Y,Z).

% Knowledge Flow
knowledge_flow(X,Z) :- collaborates(X,Y), cites(Y,Z).
knowledge_flow(X,Z) :- knowledge_flow(X,Y), collaborates(Y,Z).

% Innovation vs Tradition
innovator(X) :- cross_field(X,Y), influences(X,Y).
traditionalist(X) :- same_field(X,Y), influences(Y,X).

% Institutional Competition
competes(X,Y) :- different_institution(X,Y), same_field(X,Y).
collaborative_bridge(X,Y) :- different_institution(X,Y), collaborates(X,Y).

% Constraints on Roles
:- leader(X), follower(X).

% Dominance
dominates(X,Y) :- influences(X,Y), not influences(Y,X).
dominates(X,Z) :- dominates(X,Y), dominates(Y,Z).

% Isolation and Reach
isolated(X) :- researcher(X), not collaborates(X,Y).
well_connected(X) :- collaborates(X,Y), collaborates(Y,Z), X!=Z.

% Cycles Detection
cycle(X) :- collaborates(X,Y), collaborates(Y,Z), collaborates(Z,X).

% Authority Conflict
conflicted(X) :- leader(X), rival(X,Y).

% Knowledge Authority Constraint
:- innovator(X), traditionalist(X).

% Bridge Influence
bridge_influence(X,Z) :- collaborative_bridge(X,Y), influences(Y,Z).

% Mutual Dependency
dependent(X,Y) :- trusts(X,Y), trusts(Y,X).

% Constraint on Rival Collaboration
:- rival(X,Y), collaborates(X,Y).

% Recognition Propagation
recognized(X) :- recognized(Y), influences(X,Y).

% Institutional Influence Spread
institution_influence(I,F) :- affiliated(X,I), works_in(X,F), influences(X,Y).

% Field Dominance
field_leader(X,F) :- expert(X,F), not dominates(Y,X).

% Consistency Constraint
:- dominates(X,Y), dominates(Y,X).

% Information Bottleneck
bottleneck(X) :- knowledge_flow(Y,X), knowledge_flow(X,Z), Y!=Z.

% Isolation Constraint
:- isolated(X), leader(X).
