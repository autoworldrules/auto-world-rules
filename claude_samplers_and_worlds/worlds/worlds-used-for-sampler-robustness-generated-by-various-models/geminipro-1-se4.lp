% ==========================================
% DOMAIN BASE FACTS
% ==========================================
agent(alice).
agent(bob).
agent(charlie).
agent(diana).
agent(eve).

agency(mi6).
agency(cia).
agency(kgb).

location(london).
location(berlin).
location(moscow).

safehouse(london).
safehouse(berlin).

operation(treadstone).
operation(blackbriar).

works_for(alice, mi6).
works_for(bob, cia).
works_for(charlie, kgb).

assigned_to(alice, treadstone).
assigned_to(bob, blackbriar).

operates_in(treadstone, london).
operates_in(blackbriar, berlin).

recruits(alice, diana).
recruits(bob, eve).

% ==========================================
% RULES
% ==========================================

% 1. Spatial and operational assignments
stationed_in(X, L) :- assigned_to(X, O), operates_in(O, L).

% 2. Network connections based on operations
knows(X, Y) :- assigned_to(X, O), assigned_to(Y, O), X != Y.

% 3. Trust is a choice among known operatives
{ trusts(X, Y), suspects(X, Y) } :- knows(X, Y).

% 4. You cannot simultaneously trust and suspect someone
:- trusts(X, Y), suspects(X, Y).

% 5. Suspicion arises when interacting with known hostile agencies
suspects(X, Y) :- works_for(X, G1), works_for(Y, G2), hostile(G1, G2), knows(X, Y).

% 6. Agencies are either allied or hostile
{ allied(G1, G2), hostile(G1, G2) } :- agency(G1), agency(G2), G1 != G2.

% 7. An agency cannot be both allied and hostile to another
:- allied(G1, G2), hostile(G1, G2).

% 8. Alliances are symmetric
allied(G1, G2) :- allied(G2, G1).

% 9. Hostilities are symmetric
hostile(G1, G2) :- hostile(G2, G1).

% 10. The enemy of my ally is my enemy
hostile(G1, G3) :- allied(G1, G2), hostile(G2, G3), G1 != G3.

% 11. Agents are compromised if suspected by an agent of a hostile agency
compromised(X) :- suspects(Y, X), works_for(Y, G1), hostile(G1, G2), works_for(X, G2).

% 12. Suspicion triggers an internal investigation
investigates(Y, X) :- suspects(Y, X), agent(Y), agent(X).

% 13. Compromised agents either become moles or double agents
{ mole(X, G), double_agent(X) } :- compromised(X), works_for(X, G).

% 14. An agent cannot serve as a direct mole while operating as a double agent
:- mole(X, G), double_agent(X).

% 15. Double agents whose compromise becomes known are burned
burned(X) :- double_agent(X), compromised(X).

% 16. Burned agents are eliminated by their own investigating colleagues
eliminates(Y, X) :- burned(X), works_for(X, G), works_for(Y, G), investigates(Y, X).

% 17. Moles are protected by an unwitting colleague during investigations
protects(Y, X) :- mole(X, G), works_for(Y, G), investigates(Z, X), Y != Z.

% 18. An agent cannot be simultaneously eliminated and protected by the same operative
:- eliminates(Y, X), protects(Y, X).

% 19. Known agents may choose to meet at safehouses
{ meets_at(X, L), meets_at(Y, L) } :- knows(X, Y), safehouse(L).

% 20. Safehouses are considered secure locations
secure(L) :- safehouse(L), location(L).

% 21. A location is exposed if a compromised agent meets there
exposed(L) :- meets_at(X, L), compromised(X).

% 22. A location cannot be both secure and exposed
:- secure(L), exposed(L).

% 23. Meeting at an exposed location compromises other attendees
compromised(Y) :- meets_at(X, L), meets_at(Y, L), exposed(L), X != Y.

% 24. Recruiting establishes a handler relationship
handler(X, Y) :- recruits(X, Y).

% 25. Recruits work for the same agency as their handler
works_for(Y, G) :- handler(X, Y), works_for(X, G).

% 26. The handler-recruit relationship breeds either trust or betrayal
{ trusts(Y, X), betrays(Y, X) } :- handler(X, Y).

% 27. Double agents inevitably betray their handlers
betrays(Y, X) :- double_agent(Y), handler(X, Y).

% 28. Trust and betrayal are mutually exclusive
:- trusts(Y, X), betrays(Y, X).

% 29. Betrayal guarantees suspicion
suspects(X, Y) :- betrays(Y, X).

% 30. Suspects involved in operations become targets
target(O, Y) :- suspects(X, Y), assigned_to(X, O).

% 31. Targets are eliminated by operatives assigned to the same operational area
eliminates(X, Y) :- target(O, Y), assigned_to(X, O), operates_in(O, L), stationed_in(Y, L).

% 32. Elimination attempts result in survival or death
{ survives(Y), dead(Y) } :- eliminates(X, Y).

% 33. An agent cannot be both dead and a survivor
:- survives(Y), dead(Y).

% 34. Protection from a third party guarantees survival against an elimination attempt
survives(Y) :- protects(Z, Y), eliminates(X, Y), Z != X.

% 35. Betraying a third party ensures death during an elimination attempt
dead(Y) :- eliminates(X, Y), betrays(Z, Y), X != Z.

% 36. An agency is infiltrated if it houses a mole
infiltrated(G) :- mole(X, G).

% 37. Infiltrated agencies become hostile to the agency manipulating their mole
hostile(G1, G2) :- infiltrated(G1), works_for(Y, G2), mole(Y, G1).

% 38. Handlers investigate whoever eliminated their dead recruits
investigates(X, Z) :- handler(X, Y), dead(Y), eliminates(Z, Y).

% 39. Death officially burns an agent's operational status
burned(X) :- dead(X).

% 40. Handlers investigate their recruits if the recruit is an active target
investigates(X, Y) :- target(O, Y), active(O), handler(X, Y).

% 41. Operations with assigned agents are active
active(O) :- operation(O), assigned_to(X, O).

% 42. Active operations cannot have dead targets without being closed
:- target(O, Y), active(O), dead(Y).

% 43. Both entities in a recruitment are strictly agents
agent(X) :- recruits(X, Y).

% 44. The recruited entity is an agent
agent(Y) :- recruits(X, Y).

% 45. Locations are derived from operational theaters
location(L) :- operates_in(O, L).

% 46. Operations are valid if they occur in a location
operation(O) :- operates_in(O, L).
