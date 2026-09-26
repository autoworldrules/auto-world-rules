% ============================================================
% RULE BASE: The Deep Reef — Hydrothermal Vent Ecology
% ============================================================
%
% A network of hydrothermal vents on the ocean floor, each
% emitting chemical compounds into the water.  Organisms
% colonize vents, metabolize compounds, and form predator-prey,
% symbiotic, and competitive relationships.  Directed plumes
% carry compounds downstream, shaping which species can survive
% where.  Exclusive-property reasoning (sole_fuel, sole_emission,
% sole_dweller, etc.) propagates through three mutually recursive
% cycles across all three entity types, creating elimination
% chains that exceed the depth of both Iron Coast and NoRa.
%
% Entity types: organisms, vents, compounds  (3 types)
%
% No choice rules.  No negation-as-failure.
% ============================================================


% ────────────────────────────────────────────────────────────
%  SECTION 1 : VENT TOPOLOGY  (depth 1–2)
% ────────────────────────────────────────────────────────────
% Base fact: plume(V1,V2) — directed chemical plume from V1 to V2

% Adjacency is symmetric even though plumes are directed
adjacent(X,Y) :- plume(X,Y).
adjacent(Y,X) :- plume(X,Y).

% Downstream: transitive closure of directed plumes
downstream(X,Y) :- plume(X,Y).
downstream(X,Z) :- downstream(X,Y), plume(Y,Z), X != Z.

% Linked: symmetric transitive reachability
linked(X,Y) :- adjacent(X,Y).
linked(X,Z) :- linked(X,Y), adjacent(Y,Z), X != Z.


% ────────────────────────────────────────────────────────────
%  SECTION 2 : COMPOUND DISTRIBUTION  (depth 2–3)
% ────────────────────────────────────────────────────────────
% Base fact: emits(V,C) — vent V emits compound C
% Base fact: metabolizes(O,C) — organism O can use compound C

% A compound is present at the vent that emits it
present(C,V) :- emits(V,C).

% Compounds drift downstream through plumes
present(C,V) :- emits(V1,C), downstream(V1,V).

% Two vents share chemistry if the same compound is present at both
shared_chem(V1,V2) :- present(C,V1), present(C,V2), V1 != V2.

% A vent is enriched if two or more distinct compounds are present
enriched(V) :- present(C1,V), present(C2,V), C1 != C2.


% ────────────────────────────────────────────────────────────
%  SECTION 3 : ORGANISM DISTRIBUTION  (depth 1–4)
% ────────────────────────────────────────────────────────────
% Base fact: colonizes(O,V) — organism O lives at vent V

% Two organisms co-occur if they share a vent
co_occurs(O1,O2) :- colonizes(O1,V), colonizes(O2,V), O1 != O2.

% An organism is sustained at a vent when its metabolic needs are met
sustained(O,V) :- colonizes(O,V), metabolizes(O,C), present(C,V).

% An organism can potentially expand to a linked vent with right chemistry
expandable(O,V) :- colonizes(O,V1), linked(V1,V), metabolizes(O,C), present(C,V).

% Alternative expansion path via shared chemistry
expandable(O,V) :- colonizes(O,V1), shared_chem(V1,V), metabolizes(O,C), present(C,V).


% ────────────────────────────────────────────────────────────
%  SECTION 4 : TROPHIC RELATIONSHIPS  (depth 1–3)
% ────────────────────────────────────────────────────────────
% Base fact: hunts(O1,O2) — organism O1 preys on O2
% Base fact: bond(O1,O2) — directed base for symbiosis
% Base fact: rivalry(O1,O2) — directed base for competition

% Symbiosis is symmetric
partners(X,Y) :- bond(X,Y).
partners(Y,X) :- bond(X,Y).

% Competition is symmetric
competitor(X,Y) :- rivalry(X,Y).
competitor(Y,X) :- rivalry(X,Y).

% Exploiters are also competitors
competitor(O1,O2) :- exploiter(O1,O2).

% Predation chain: transitive closure
prey_chain(X,Y) :- hunts(X,Y).
prey_chain(X,Z) :- hunts(X,Y), prey_chain(Y,Z), X != Z.

% Resource rivalry: two organisms using the same compound at the same vent
resource_rival(O1,O2) :- metabolizes(O1,C), metabolizes(O2,C), colonizes(O1,V), colonizes(O2,V), O1 != O2.

% Apparent competition: two organisms sharing a predator at the same vent
apparent_rival(O1,O2) :- hunts(P,O1), hunts(P,O2), colonizes(O1,V), colonizes(O2,V), O1 != O2.

% Cascade-linked organisms that co-occur are also apparent rivals
apparent_rival(O1,O3) :- cascade(O1,O3), co_occurs(O1,O3).

% Trophic cascade: O1 indirectly benefits O3 by hunting O2 which hunts O3
cascade(O1,O3) :- hunts(O1,O2), hunts(O2,O3), O1 != O3.

% Exploiter: organism that hunts the same prey as a resource rival
exploiter(O1,O2) :- hunts(O1,S), hunts(O2,S), resource_rival(O1,O2), O1 != O2.


% ────────────────────────────────────────────────────────────
%  SECTION 5 : EXCLUSIVE PROPERTIES — DEFINITIONS & CONSTRAINTS
% ────────────────────────────────────────────────────────────
%
% These properties encode uniqueness or absence.
% They may be given as base facts or derived by propagation
% rules in Section 6.  Constraints enforce consistency.
%
% Organism-level:
%   no_predator(O)       — nothing hunts O
%   no_prey(O)           — O hunts nothing
%   sole_fuel(O,C)       — C is the only compound O metabolizes
%   sole_quarry(P,O)     — O is the only organism P hunts
%   sole_hunter(P,O)     — P is the only organism that hunts O
%   sole_colony(O,V)     — V is the only vent O colonizes
%   no_partner(O)        — O has no symbiont
%   no_rival(O)          — O has no competitor
%
% Vent-level:
%   sole_emission(V,C)   — C is the only compound V emits
%   sole_dweller(V,O)    — O is the only organism at V
%
% Compound-level:
%   sole_source(C,V)     — V is the only vent that emits C
%   sole_user(C,O)       — O is the only organism that metabolizes C

% Organism-level constraints
:- no_predator(O), hunts(X,O).
:- no_prey(O), hunts(O,X).
:- sole_fuel(O,C), metabolizes(O,C2), C != C2.
:- sole_quarry(P,O), hunts(P,O2), O != O2.
:- sole_hunter(P,O), hunts(P2,O), P != P2.
:- sole_colony(O,V), colonizes(O,V2), V != V2.
:- no_partner(O), partners(O,X).
:- no_rival(O), competitor(O,X).

% Vent-level constraints
:- sole_emission(V,C), emits(V,C2), C != C2.
:- sole_dweller(V,O), colonizes(O2,V), O != O2.

% Compound-level constraints
:- sole_source(C,V), emits(V2,C), V != V2.
:- sole_user(C,O), metabolizes(O2,C), O != O2.


% ────────────────────────────────────────────────────────────
%  SECTION 6 : EXCLUSIVE PROPERTY PROPAGATION  (depth 2–5)
% ────────────────────────────────────────────────────────────
%
% Three mutually recursive cycles propagate exclusivity
% across entity types, creating hard elimination reasoning.
%
% Cycle A: sole_fuel ↔ sole_emission  (organism ↔ vent)
% Cycle B: sole_colony ↔ sole_source  (organism ↔ compound)
% Cycle C: sole_dweller ↔ sole_user   (vent ↔ compound)
%
% Cross-links connect the three cycles.

% ── Cycle A: sole_fuel ↔ sole_emission ──

% If V has a sole dweller O, and V has a sole emission C,
% and O metabolizes C, then C is O's sole fuel
sole_fuel(O,C) :- sole_dweller(V,O), sole_emission(V,C), metabolizes(O,C).

% If V has a sole dweller O, and O has a sole fuel C,
% and V emits C, then C is V's sole emission
sole_emission(V,C) :- sole_dweller(V,O), sole_fuel(O,C), emits(V,C).

% ── Cycle B: sole_colony ↔ sole_source ──

% If O has sole fuel C, and C has sole source V,
% and O colonizes V, then V is O's sole colony
sole_colony(O,V) :- sole_fuel(O,C), sole_source(C,V), colonizes(O,V).

% If O has sole colony V, and O has sole fuel C,
% and V emits C, then V is C's sole source
sole_source(C,V) :- sole_colony(O,V), sole_fuel(O,C), emits(V,C).

% ── Cycle C: sole_dweller ↔ sole_user ──

% If C has sole user O, and C has sole source V,
% and O colonizes V, then O is V's sole dweller
sole_dweller(V,O) :- sole_user(C,O), sole_source(C,V), colonizes(O,V).

% If V has sole dweller O, and V has sole emission C,
% and O metabolizes C, then O is C's sole user
sole_user(C,O) :- sole_dweller(V,O), sole_emission(V,C), metabolizes(O,C).

% ── Cross-links between cycles ──

% Partners propagate sole_fuel: if O1 has sole fuel C, and O2 is
% O1's partner at the same vent, and O2 also metabolizes C
sole_fuel(O2,C) :- sole_fuel(O1,C), partners(O1,O2), metabolizes(O2,C), sole_dweller(V,O1), colonizes(O2,V).

% Downstream sole emission propagation
sole_source(C,V1) :- sole_emission(V1,C), sole_emission(V2,C), downstream(V1,V2).

% ── Derived absence from exclusivity ──

% If O has sole colony V, and V has sole dweller O,
% then O has nothing to hunt (no other organisms present)
no_prey(O) :- sole_colony(O,V), sole_dweller(V,O).

% If sole colony and sole dweller both hold, O is completely isolated
no_predator(O) :- sole_dweller(V,O), sole_colony(O,V), no_prey(O).

% No partner if you are a sole dweller at your only colony
no_partner(O) :- sole_dweller(V,O), sole_colony(O,V).

% No rival if you are a sole dweller at your only colony
no_rival(O) :- sole_dweller(V,O), sole_colony(O,V).


% ────────────────────────────────────────────────────────────
%  SECTION 7 : ECOLOGICAL ROLES  (depth 3–6)
% ────────────────────────────────────────────────────────────

% Apex predator: nothing hunts it
apex(O) :- no_predator(O), colonizes(O,V).

% Basal organism: hunts nothing (feeds only on compounds)
basal(O) :- no_prey(O), colonizes(O,V).

% Specialist predator: hunts only one species
specialist(P) :- sole_quarry(P,O), hunts(P,O).

% Generalist predator: hunts two or more species
generalist(O) :- hunts(O,S1), hunts(O,S2), S1 != S2.

% Obligate chemotroph: metabolizes only one compound
obligate(O) :- sole_fuel(O,C), metabolizes(O,C).

% Mesopredator: hunts something AND is itself hunted
mesopredator(O) :- hunts(O,S), hunts(P,O), S != P.

% Keystone predator: sole predator of a species that has competitors
keystone(P) :- sole_hunter(P,O), hunts(P,O), competitor(O,S), S != P.

% A network anchor can also act as a keystone
keystone(O) :- network_anchor(O), sole_hunter(O,S), hunts(O,S), competitor(S,X).

% Foundation species: basal organism that is a partner to a predator
foundation(O) :- basal(O), partners(O,S), hunts(S,X).

% Obligate prey: O is both the sole quarry of P and P is O's sole predator
obligate_prey(O) :- sole_hunter(P,O), sole_quarry(P,O), hunts(P,O).


% ────────────────────────────────────────────────────────────
%  SECTION 8 : VENT CHARACTERIZATION  (depth 4–7)
% ────────────────────────────────────────────────────────────

% Hotspot: a vent hosting both an apex and a basal organism
hotspot(V) :- colonizes(O1,V), colonizes(O2,V), apex(O1), basal(O2), O1 != O2.

% A tension zone with a basal organism is also a hotspot
hotspot(V) :- tension(V), colonizes(O,V), basal(O).

% Fragile: a vent whose sole dweller is obligate
fragile(V) :- sole_dweller(V,O), obligate(O).

% Nexus: a vent linked to two vents with different emitted compounds
nexus(V) :- linked(V,V1), linked(V,V2), emits(V1,C1), emits(V2,C2), C1 != C2, V1 != V2.

% Hub: an enriched nexus
hub(V) :- enriched(V), nexus(V).

% An enriched bridge is also a hub
hub(V) :- bridge(V), enriched(V).

% Refuge: a vent with no predators present (all colonizers lack threats)
refuge(V) :- colonizes(O1,V), colonizes(O2,V), basal(O1), no_predator(O2), O1 != O2.

% Threatened: a vent where a keystone predator could leave
threatened(V) :- colonizes(O,V), keystone(O), expandable(O,V2), V != V2.

% Tension: a vent where an apex and a keystone compete for resources
tension(V) :- colonizes(O1,V), colonizes(O2,V), apex(O1), keystone(O2), resource_rival(O1,O2), O1 != O2.

% Apex web at a shared vent also creates tension
tension(V) :- apex_web(O1,O2), colonizes(O1,V), colonizes(O2,V).


% ────────────────────────────────────────────────────────────
%  SECTION 9 : ORGANISM INTERACTIONS  (depth 5–8)
% ────────────────────────────────────────────────────────────

% Dependent: O1 depends on partner O2 for its sole fuel
dependent(O1,O2) :- partners(O1,O2), sole_fuel(O1,C), metabolizes(O2,C), co_occurs(O1,O2).

% Vulnerable: an apex predator that depends on another organism
vulnerable(O) :- apex(O), dependent(O,S).

% An isolated specialist with sole colony is also vulnerable
vulnerable(O) :- isolated_specialist(O), sole_colony(O,V).

% Dominant: an apex predator at a hotspot
dominant(O) :- apex(O), colonizes(O,V), hotspot(V).

% A generalist apex at a hotspot is also dominant
dominant(O) :- generalist(O), apex(O), colonizes(O,V), hotspot(V).

% Controller: dominant organism that is also a keystone
controller(O) :- dominant(O), keystone(O).

% Bottleneck: an organism that is both a foundation and obligate prey
bottleneck(O) :- foundation(O), obligate_prey(O).

% Stable pair: two partner organisms, both sustained, at the same vent
stable_pair(O1,O2) :- partners(O1,O2), sustained(O1,V), sustained(O2,V).


% ────────────────────────────────────────────────────────────
%  SECTION 10 : NETWORK STRUCTURE  (depth 7–10)
% ────────────────────────────────────────────────────────────

% Corridor: two linked vents sharing a stable pair
corridor(V1,V2) :- stable_pair(O1,O2), colonizes(O1,V1), colonizes(O2,V1), colonizes(O1,V2), colonizes(O2,V2), linked(V1,V2).

% Sentinel: a mesopredator at a hub
sentinel(O) :- colonizes(O,V), hub(V), mesopredator(O).

% A warden-mesopredator at a hub is also a sentinel
sentinel(O) :- warden(O), colonizes(O,V), hub(V), mesopredator(O).

% Anchor: a foundation organism at a nexus
anchor(O) :- foundation(O), colonizes(O,V), nexus(V).

% Guardian: apex predator at a hub protecting a foundation species
guardian(O1) :- apex(O1), colonizes(O1,V), hub(V), hunts(O1,S), competitor(S,O2), foundation(O2), colonizes(O2,V).

% Cascade risk: a vent where a controller hunts a bottleneck
cascade_risk(V) :- colonizes(O1,V), colonizes(O2,V), controller(O1), bottleneck(O2), hunts(O1,O2).

% A threatened vent with a bottleneck also has cascade risk
cascade_risk(V) :- threatened(V), colonizes(O,V), bottleneck(O).

% Safe harbor: a refuge with a corridor to a hotspot
safe_harbor(V) :- refuge(V), corridor(V,V2), hotspot(V2).

% A rescue corridor leading to a refuge is also a safe harbor
safe_harbor(V2) :- rescue_corridor(V1,V2), refuge(V2).

% Apex web: two apex predators linked through a shared prey chain target
apex_web(O1,O2) :- apex(O1), apex(O2), prey_chain(O1,S), prey_chain(O2,S), O1 != O2.


% ────────────────────────────────────────────────────────────
%  SECTION 11 : DEEP DERIVATIONS  (depth 9–14+)
% ────────────────────────────────────────────────────────────

% Regulator: a sentinel that is also a keystone (depth ~9)
regulator(O) :- sentinel(O), keystone(O).

% Warden: a guardian at a vent with a corridor (depth ~10)
warden(O) :- guardian(O), colonizes(O,V), corridor(V,V2).

% Linchpin: a controller whose sole quarry is an anchor (depth ~10)
linchpin(O) :- controller(O), sole_quarry(O,S), anchor(S).

% Critical vent: has both a regulator and a bottleneck (depth ~10)
critical(V) :- colonizes(O1,V), colonizes(O2,V), regulator(O1), bottleneck(O2), O1 != O2.

% Fulcrum: a bottleneck at a critical vent that is also an anchor (depth ~11)
fulcrum(O) :- bottleneck(O), anchor(O), colonizes(O,V), critical(V).

% Steward: a regulator at a critical vent with a corridor to safe harbor (depth ~12)
steward(O) :- regulator(O), colonizes(O,V), critical(V), corridor(V,V2), safe_harbor(V2).

% Architect: a linchpin whose sole quarry is a fulcrum (depth ~13)
architect(O) :- linchpin(O), sole_quarry(O,S), fulcrum(S).

% Keystone cascade: a critical vent where a steward's prey chain reaches
% a fulcrum (depth ~14)
keystone_cascade(V) :- colonizes(O1,V), steward(O1), colonizes(O2,V), fulcrum(O2), prey_chain(O1,O2).

% An architect at a vent with a bottleneck also signals keystone cascade
keystone_cascade(V) :- colonizes(O,V), architect(O), colonizes(O2,V), bottleneck(O2), prey_chain(O,O2).


% ────────────────────────────────────────────────────────────
%  SECTION 12 : CROSS-CUTTING INTERACTIONS  (depth 6–12)
% ────────────────────────────────────────────────────────────

% Compound broker: metabolizes a compound at one vent, partner does at another
broker(O1,C) :- metabolizes(O1,C), colonizes(O1,V1), partners(O1,O2), metabolizes(O2,C), colonizes(O2,V2), linked(V1,V2), V1 != V2.

% Compound bridge: a vent where a broker connects two compound communities
bridge(V) :- colonizes(O,V), broker(O,C1), broker(O,C2), C1 != C2.

% Isolated specialist: specialist predator at a fragile vent
isolated_specialist(O) :- specialist(O), colonizes(O,V), fragile(V).

% Trapped: obligate organism at a fragile vent with no alternative colony
trapped(O) :- obligate(O), colonizes(O,V), fragile(V), sole_colony(O,V).

% Vulnerable organisms at fragile vents are also trapped
trapped(O) :- vulnerable(O), sole_colony(O,V), fragile(V).

% Rescue corridor: a corridor from a fragile vent to a hub
rescue_corridor(V1,V2) :- fragile(V1), corridor(V1,V2), hub(V2).

% Network anchor: an anchor with corridors from multiple vents
network_anchor(O) :- anchor(O), colonizes(O,V1), colonizes(O,V2), corridor(V1,V3), corridor(V2,V4), V1 != V2.


% ────────────────────────────────────────────────────────────
%  CONSTRAINTS
% ────────────────────────────────────────────────────────────

% No self-predation
:- hunts(X,X).

% No self-symbiosis
:- bond(X,X).

% No self-competition
:- rivalry(X,X).

% No self-loops in plume topology
:- plume(X,X).

% Cannot hunt your symbiont
:- hunts(X,Y), bond(X,Y).
:- hunts(X,Y), bond(Y,X).

% No mutual predation
:- hunts(X,Y), hunts(Y,X).

% Cannot be both competitor and partner
:- competitor(X,Y), partners(X,Y).

% A predator with sole colony must co-occur with its prey
:- hunts(O1,O2), sole_colony(O1,V1), sole_colony(O2,V2), V1 != V2.

% Sole colony organisms cannot expand elsewhere
:- sole_colony(O,V), expandable(O,V2), V != V2.

% Sole dweller vent cannot also host a predator of the dweller
:- sole_dweller(V,O), hunts(P,O), colonizes(P,V).
