% ============================================================
% RULE BASE: The Iron Coast — Maritime Trade & Piracy
% ============================================================
%
% A treacherous archipelago where captains sail ships between
% island ports, carrying trade goods.  Governors control
% islands and levy authority over ports.  Alliances and
% hostilities shape economics, military strategy, and
% political power across the seas.
%
% Entity types: persons, islands, ports, ships, goods
% ~50 derivation rules, ~20 constraints, depth 10+
%
% No negation-as-failure.  No choice rules.  No underscores.
% ============================================================

% ────────────────────────────────────────────────────────────
%  SECTION 1 : SYMMETRY  (from one-directional base facts)
% ────────────────────────────────────────────────────────────
% Base facts use one-directional forms (passage, pact, feud).
% Rules below derive the symmetric relations the rest of the
% rule base relies on.

route(X,Y) :- passage(X,Y).
route(Y,X) :- passage(X,Y).

allied(X,Y) :- pact(X,Y).
allied(Y,X) :- pact(X,Y).

hostile(X,Y) :- feud(X,Y).
hostile(Y,X) :- feud(X,Y).

% ────────────────────────────────────────────────────────────
%  SECTION 2 : GEOGRAPHY  (depth 1-2)
% ────────────────────────────────────────────────────────────

% Reachability: transitive closure of routes
reachable(X,Y) :- route(X,Y).
reachable(X,Z) :- reachable(X,Y), route(Y,Z), X != Z.

% Neighbors share a direct route
neighbors(X,Y) :- route(X,Y), X != Y.

% Coastal: an island that has at least one port
coastal(I,I) :- port(P,I).

% ────────────────────────────────────────────────────────────
%  SECTION 3 : PRESENCE & CONTROL  (depth 1-3)
% ────────────────────────────────────────────────────────────

% Where a person physically is (3-way join)
stationed(X,I) :- captain(X,S), docked(S,P), port(P,I).
stationed(X,I) :- crew(X,S), docked(S,P), port(P,I).

% Port control flows from island governance
controls(X,P) :- governs(X,I), port(P,I).

% Authority = governance or port control
authority(X,I) :- governs(X,I).
authority(X,I) :- controls(X,P), port(P,I).

% Colocated: two people at the same island
colocated(X,Y) :- stationed(X,I), stationed(Y,I), X != Y.

% Subordinate: crew whose captain governs the island they're on
subordinate(X,Y) :- crew(X,S), captain(Y,S), governs(Y,I), stationed(X,I).

% ────────────────────────────────────────────────────────────
%  SECTION 4 : SHIP REACH  (depth 2-3)
% ────────────────────────────────────────────────────────────

% A ship can access an island it's already at
accessible(S,I) :- docked(S,P), port(P,I).
% ... or any island reachable from its current port
accessible(S,I) :- docked(S,P), port(P,J), reachable(J,I).

% A captain's operational range
range(X,I) :- captain(X,S), accessible(S,I).

% A crew member's range follows their ship
range(X,I) :- crew(X,S), accessible(S,I).

% ────────────────────────────────────────────────────────────
%  SECTION 5 : SUPPLY & TRADE  (depth 3-4)
% ────────────────────────────────────────────────────────────

% An island is supplied with a good when a carrying ship can reach it
supplied(I,G) :- carries(S,G), accessible(S,I).

% Commerce: one island produces what another demands, and they're connected
commerce(I1,I2) :- produces(I1,G), demands(I2,G), reachable(I1,I2).

% Mutual exchange: both directions of commerce
exchange(I1,I2) :- commerce(I1,I2), commerce(I2,I1).

% Trade hub: an island with commerce to 2+ different islands
hub(I,I) :- commerce(I,J1), commerce(I,J2), J1 != J2.

% Entrepot: a hub that is also a destination of commerce
entrepot(I,I) :- hub(I,I), commerce(J,I).

% ────────────────────────────────────────────────────────────
%  SECTION 6 : ECONOMICS & PROFIT  (depth 4-5)
% ────────────────────────────────────────────────────────────

% A captain profits from carrying a good to a demanding island
profits(X,G) :- captain(X,S), carries(S,G), accessible(S,I), demands(I,G).

% A governor profits from satisfied demand
profits(X,G) :- governs(X,I), demands(I,G), supplied(I,G).

% A governor profits from exports
profits(X,G) :- governs(X,I), produces(I,G), commerce(I,J).

% Two people profiting from the same good become trade partners
partner(X,Y) :- profits(X,G), profits(Y,G), X != Y.

% Wealthy: profits from two or more different goods
wealthy(X,X) :- profits(X,G1), profits(X,G2), G1 != G2.

% Patron: wealthy ally of a captain
patron(X,Y) :- wealthy(X,X), allied(X,Y), captain(Y,S).

% Beneficiary: crew of a ship that carries profitable goods
beneficiary(X,G) :- crew(X,S), carries(S,G), accessible(S,I), demands(I,G).

% ────────────────────────────────────────────────────────────
%  SECTION 7 : POWER & INFLUENCE  (depth 5-7)
% ────────────────────────────────────────────────────────────

% Influential: wealthy AND a governor
influential(X,X) :- wealthy(X,X), governs(X,I).

% Dominates: controls a port where another's ship is stuck
dominates(X,Y) :- controls(X,P), docked(S,P), captain(Y,S), X != Y.

% Dominates: also if you control a port with their crew's ship
dominates(X,Y) :- controls(X,P), docked(S,P), crew(Y,S), X != Y.

% Overshadows: influential AND dominates
overshadows(X,Y) :- influential(X,X), dominates(X,Y).

% Leverage: your island produces what their island needs
leverage(X,Y) :- governs(X,I1), produces(I1,G), governs(Y,I2), demands(I2,G), reachable(I1,I2), X != Y.

% Magnate: wealthy with leverage over someone
magnate(X,X) :- wealthy(X,X), leverage(X,Y).

% ────────────────────────────────────────────────────────────
%  SECTION 8 : CONFLICT  (depth 4-6)
% ────────────────────────────────────────────────────────────

% Rivals: hostile AND economically entangled
rival(X,Y) :- hostile(X,Y), partner(X,Y).

% Rivals: hostile AND one dominates
rival(X,Y) :- hostile(X,Y), dominates(X,Y).

% Rival is symmetric
rival(Y,X) :- rival(X,Y).

% Threatens: hostile to an island's governor AND can reach it
threatens(X,I) :- hostile(X,Y), governs(Y,I), range(X,I), X != Y.

% Contested: two or more people threaten the same island
contested(I,I) :- threatens(X,I), threatens(Y,I), X != Y.

% Besieged: contested AND the governor is dominated by a threatener
besieged(I,I) :- contested(I,I), governs(X,I), dominates(Y,X), threatens(Y,I).

% Blockaded port: hostile person controls a port on a neighboring island
blockaded(P,P) :- port(P,I), governs(Y,I), hostile(X,Y), controls(X,Q), port(Q,J), neighbors(I,J).

% ────────────────────────────────────────────────────────────
%  SECTION 9 : ALLIANCES & DIPLOMACY  (depth 2-8)
% ────────────────────────────────────────────────────────────

% Alliance chain (transitive trust)
linked(X,Y) :- allied(X,Y).
linked(X,Z) :- linked(X,Y), allied(Y,Z), X != Z.

% Shared interest: linked AND profiting from the same good
mutual(X,Y) :- profits(X,G), profits(Y,G), linked(X,Y), X != Y.

% Power bloc: both influential AND linked
bloc(X,Y) :- influential(X,X), influential(Y,Y), linked(X,Y), X != Y.

% Protects: allied to governor AND stationed within reach
protects(X,I) :- allied(X,Y), governs(Y,I), range(X,I), X != Y.

% Defended: protected by an influential person
defended(I,I) :- protects(X,I), influential(X,X).

% ────────────────────────────────────────────────────────────
%  SECTION 10 : STRATEGIC ROLES  (depth 6-10)
% ────────────────────────────────────────────────────────────

% Trader: profits AND has partners
trader(X,X) :- profits(X,G), partner(X,Y).

% Diplomat: linked to two rivals (bridge between enemies)
diplomat(X,X) :- linked(X,Y), linked(X,Z), rival(Y,Z), X != Y, X != Z, Y != Z.

% Emissary: allied to an influential person, stationed at their island
emissary(X,Y) :- allied(X,Y), influential(Y,Y), governs(Y,I), stationed(X,I), X != Y.

% Hegemon: both magnate AND diplomat (depth ~8)
hegemon(X,X) :- magnate(X,X), diplomat(X,X).

% Envoy: emissary of a hegemon (depth ~9)
envoy(X,X) :- emissary(X,Y), hegemon(Y,Y).

% Liberator: envoy who protects a besieged island (depth ~10)
liberator(X,I) :- envoy(X,X), protects(X,I), besieged(I,I).

% Peacemaker: linked to both sides of a contested island
peacemaker(X,I) :- linked(X,Y), linked(X,Z), threatens(Y,I), threatens(Z,I), X != Y, X != Z, Y != Z.

% Arbiter: diplomat AND peacemaker
arbiter(X,I) :- diplomat(X,X), peacemaker(X,I).

% ────────────────────────────────────────────────────────────
%  SECTION 11 : ECONOMIC CHAINS  (depth 5-8)
% ────────────────────────────────────────────────────────────

% Dependent: your island demands a good and only hostile islands produce it
dependent(X,G) :- governs(X,I), demands(I,G), produces(J,G), hostile(X,Y), governs(Y,J).

% Exposed: dependent on a good AND the supply route is contested
exposed(X,G) :- dependent(X,G), governs(X,I), contested(I,I).

% Strangled: exposed AND besieged
strangled(X,G) :- exposed(X,G), governs(X,I), besieged(I,I).

% Embargo: governor who is hostile to all who profit from a good they need
embargo(X,Y) :- demands(I,G), governs(X,I), profits(Y,G), hostile(X,Y), X != Y.

% Sanctions: rivals who both have leverage over each other
sanctions(X,Y) :- leverage(X,Y), leverage(Y,X), hostile(X,Y).

% ────────────────────────────────────────────────────────────
%  SECTION 12 : CREW DYNAMICS  (depth 3-6)
% ────────────────────────────────────────────────────────────

% Shipmates: two crew on the same ship
shipmates(X,Y) :- crew(X,S), crew(Y,S), X != Y.

% Loyal: crew allied with their captain
loyal(X,Y) :- crew(X,S), captain(Y,S), allied(X,Y).

% Disgruntled: crew hostile to their captain
disgruntled(X,Y) :- crew(X,S), captain(Y,S), hostile(X,Y).

% Operative: crew stationed at an island governed by an ally of their captain
operative(X,I) :- crew(X,S), captain(Y,S), allied(Y,Z), governs(Z,I), stationed(X,I), Y != Z.

% ────────────────────────────────────────────────────────────
%  CONSTRAINTS
% ────────────────────────────────────────────────────────────

% Cannot be both hostile and allied (at base level)
:- feud(X,Y), pact(X,Y).
:- hostile(X,Y), allied(X,Y).

% No self-hostility or self-alliance
:- feud(X,X).
:- pact(X,X).

% No self-routes
:- passage(X,X).

% A person captains at most one ship
:- captain(X,S1), captain(X,S2), S1 != S2.

% A ship has at most one captain
:- captain(X,S), captain(Y,S), X != Y.

% A person governs at most one island
:- governs(X,I1), governs(X,I2), I1 != I2.

% An island has at most one governor
:- governs(X,I), governs(Y,I), X != Y.

% A ship is docked at at most one port
:- docked(S,P1), docked(S,P2), P1 != P2.

% A port belongs to exactly one island
:- port(P,I1), port(P,I2), I1 != I2.

% Cannot be both captain and crew of the same ship
:- captain(X,S), crew(X,S).

% A person cannot be crew on two different ships
:- crew(X,S1), crew(X,S2), S1 != S2.

% An island cannot both produce and demand the same good
:- produces(I,G), demands(I,G).

% Hostile persons cannot share a ship
:- captain(X,S), crew(Y,S), feud(X,Y).
:- crew(X,S), crew(Y,S), feud(X,Y), X != Y.
