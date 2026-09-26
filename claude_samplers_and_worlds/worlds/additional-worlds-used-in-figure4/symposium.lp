% ============================================================
% RULE BASE: The Symposium
% Scholarly Orders, Ancient Libraries & the Politics of Knowledge
% ============================================================
%
% An ancient world of scholarly orders scattered across city-states
% connected by roads. Scholars study disciplines, mentor apprentices,
% scribe manuscripts, and compete for influence. Orders form
% alliances or feuds. Libraries hold manuscripts that are keys to
% knowledge. Patronage, endorsement, and institutional politics
% determine who holds intellectual and political power.
%
% Entity types: scholars, orders, libraries, manuscripts,
%               disciplines, cities
%
% Structural complexity sources:
%   - Derivation depth 12-14 (vs Iron Coast ~10)
%   - Cross-system multi-way joins (knowledge + politics + geography)
%   - Negative/exclusion reasoning with base-fact negation
%   - Bidirectional derivation paths
%   - Constraint-driven disambiguation
%   - Multiple alternative derivation routes to same predicate
%
% No choice rules. No negation-as-failure. No numerical values.
% ============================================================

% ────────────────────────────────────────────────────────────
%  SECTION 1 : SYMMETRY  (depth 1)
% ────────────────────────────────────────────────────────────

path(X,Y) :- road(X,Y).
path(Y,X) :- road(X,Y).

allies(X,Y) :- alliance(X,Y).
allies(Y,X) :- alliance(X,Y).

rivals(X,Y) :- rivalry(X,Y).
rivals(Y,X) :- rivalry(X,Y).

% ────────────────────────────────────────────────────────────
%  SECTION 2 : GEOGRAPHY  (depth 1-3)
% ────────────────────────────────────────────────────────────

% Transitive closure of paths
connected(X,Y) :- path(X,Y).
connected(X,Z) :- connected(X,Y), path(Y,Z), X != Z.

% Direct neighbors
neighbors(X,Y) :- path(X,Y), X != Y.

% Two scholars in the same city
colocated(X,Y) :- resides(X,C), resides(Y,C), X != Y.

% Cities a scholar can physically reach (including their own)
accessible(P,C) :- resides(P,C).
accessible(P,D) :- resides(P,C), connected(C,D).

% ────────────────────────────────────────────────────────────
%  SECTION 3 : SCHOLARLY LINEAGE  (depth 1-4)
% ────────────────────────────────────────────────────────────

% Bidirectional: mentors and protege are inverses
protege(Y,X) :- mentors(X,Y).
mentors(X,Y) :- protege(Y,X).

% Transitive mentorship chain
lineage(X,Y) :- mentors(X,Y).
lineage(X,Z) :- lineage(X,Y), mentors(Y,Z), X != Z.

% Peers: share a direct mentor
peer(X,Y) :- mentors(Z,X), mentors(Z,Y), X != Y.

% Co-lineage: share an ancestor in the mentorship tree
colineage(X,Y) :- lineage(Z,X), lineage(Z,Y), X != Y.

% Elder: grandmentor (mentor of one's mentor)
elder(X,Y) :- mentors(X,Z), mentors(Z,Y).

% Academic siblings: peers who study the same discipline
acadsib(X,Y) :- peer(X,Y), studies(X,D), studies(Y,D).

% ────────────────────────────────────────────────────────────
%  SECTION 4 : KNOWLEDGE ACCESS  (depth 2-7)
% ────────────────────────────────────────────────────────────

% Access to manuscripts via reachable libraries
canaccess(P,M) :- accessible(P,C), houses(L,C), holds(L,M).

% Learned: studies the discipline AND can access a relevant manuscript
learned(P,D) :- studies(P,D), canaccess(P,M), covers(M,D).

% Deep learning: learned AND one's mentor is also learned in that discipline
deeplearned(P,D) :- learned(P,D), mentors(Q,P), learned(Q,D).

% Polymath: learned in two or more distinct disciplines
polymath(P,P) :- learned(P,D1), learned(P,D2), D1 != D2.

% Expert: deep learning AND authored a manuscript on the discipline
expert(P,D) :- deeplearned(P,D), scribed(P,M), covers(M,D).

% Luminary: expert endorsed by another expert in the same discipline
luminary(P,D) :- expert(P,D), endorsed(Q,P), expert(Q,D), P != Q.

% Certified: endorsed by one's own mentor AND learned in the discipline
certified(P,D) :- endorsed(Q,P), mentors(Q,P), learned(P,D).

% Authority: luminary who also heads an order
authoritative(P,D) :- luminary(P,D), head(P,O).

% ────────────────────────────────────────────────────────────
%  SECTION 5 : ORDER DYNAMICS  (depth 1-5)
% ────────────────────────────────────────────────────────────

% Fellow: member of the same order
fellow(X,Y) :- member(X,O), member(Y,O), X != Y.

% Cross-order: belongs to two or more orders
crossorder(X,X) :- member(X,O1), member(X,O2), O1 != O2.

% Order-allied: members of allied orders
orderallied(X,Y) :- member(X,O1), member(Y,O2), allies(O1,O2), X != Y.

% Order-rival: members of rival orders
orderrival(X,Y) :- member(X,O1), member(Y,O2), rivals(O1,O2), X != Y.

% Delegate: member endorsed by the head of their own order
delegate(X,O) :- member(X,O), head(Y,O), endorsed(Y,X), X != Y.

% Emissary: delegate residing in a different city from their head
emissary(X,O) :- delegate(X,O), head(Y,O), resides(X,C1), resides(Y,C2), C1 != C2, X != Y.

% ────────────────────────────────────────────────────────────
%  SECTION 6 : PATRONAGE & INFLUENCE  (depth 2-7)
% ────────────────────────────────────────────────────────────

% Bidirectional: patron and ward are inverses
ward(Y,X) :- patron(X,Y).
patron(X,Y) :- ward(Y,X).

% Transitive patronage chain
supports(X,Y) :- patron(X,Y).
supports(X,Z) :- supports(X,Y), patron(Y,Z), X != Z.

% Sponsor: patron who is also a fellow (same order)
sponsor(X,Y) :- patron(X,Y), fellow(X,Y).

% Influential: patron of a head of any order
influential(X,X) :- patron(X,Y), head(Y,O).

% Broker: influential AND cross-order
broker(X,X) :- influential(X,X), crossorder(X,X).

% Kingmaker: patron of heads of two different orders
kingmaker(X,X) :- patron(X,Y), patron(X,Z), head(Y,O1), head(Z,O2), O1 != O2, Y != Z.

% Sway: patronage chain reaches a luminary in a discipline
sway(X,D) :- supports(X,Y), luminary(Y,D).

% Benefactor: patron of someone in a rival order
benefactor(X,Y) :- patron(X,Y), orderrival(X,Y).

% Indebted: ward who is also a fellow of their patron
indebted(X,Y) :- ward(X,Y), fellow(X,Y).

% ────────────────────────────────────────────────────────────
%  SECTION 7 : LIBRARIES & MANUSCRIPTS  (depth 2-9)
% ────────────────────────────────────────────────────────────

% Repository: library covering a particular discipline
repository(L,D) :- holds(L,M), covers(M,D).

% Center of learning: city with a repository AND a resident expert
center(C,D) :- houses(L,C), repository(L,D), resides(P,C), expert(P,D).

% Prestigious: library whose founder is an expert in a discipline it covers
prestigious(L,L) :- founded(P,L), repository(L,D), expert(P,D).

% Contested library: in a city where rival order members both reside
contestedlib(L,L) :- houses(L,C), resides(X,C), resides(Y,C), orderrival(X,Y).

% Seminal: manuscript whose author is a luminary in the discipline
seminal(M,D) :- scribed(P,M), covers(M,D), luminary(P,D).

% Rare: sole surviving copy of a seminal manuscript
rare(M,M) :- sole_copy(M,L), seminal(M,D).

% ────────────────────────────────────────────────────────────
%  SECTION 8 : CONFLICT & DISPUTES  (depth 4-9)
% ────────────────────────────────────────────────────────────

% Adversary: order rivals who share a lineage ancestor
adversary(X,Y) :- orderrival(X,Y), colineage(X,Y).

% Adversary is symmetric
adversary(Y,X) :- adversary(X,Y).

% Dispute: experts in the same discipline from rival orders
dispute(X,Y) :- expert(X,D), expert(Y,D), orderrival(X,Y).

% Contested discipline: discipline under dispute
contesteddisc(D,D) :- dispute(X,Y), expert(X,D), expert(Y,D).

% Schism: a dispute between mentor and mentee
schism(X,Y) :- dispute(X,Y), mentors(X,Y).
schism(X,Y) :- dispute(X,Y), mentors(Y,X).

% Defector: member endorsed by the head of a rival order
defector(X,O) :- member(X,O), head(Y,O2), endorsed(Y,X), rivals(O,O2), X != Y.

% Undermined: a head whose delegate is endorsed by a rival head
undermined(X,O) :- head(X,O), delegate(Y,O), endorsed(Z,Y), head(Z,O2), rivals(O,O2), X != Y, X != Z.

% Threatened: an order whose head has an influential adversary
threatened(O,O) :- head(X,O), adversary(Y,X), influential(Y,Y).

% Embattled: an order that is both threatened and undermined
embattled(O,O) :- threatened(O,O), undermined(X,O).

% ────────────────────────────────────────────────────────────
%  SECTION 9 : NEGATIVE / EXCLUSION REASONING  (depth 3-10)
% ────────────────────────────────────────────────────────────
%
% Negative base facts (stated explicitly, never derived by NAF):
%   no_apprentices(X,X) - X mentors nobody
%   sole_discipline(X,D) - X studies only discipline D
%   unaffiliated(X,X)    - X belongs to no order
%   no_head(O,O)         - order O has no current leader
%   sole_copy(M,L)       - L has the only surviving copy of M
%   no_patron(X,X)       - nobody patronizes X
%   no_endorsers(X,X)    - nobody has endorsed X
%   sole_order(X,O)      - X belongs to only order O
%
% These combine with positive derivation chains to produce
% deep inferences (depth 8-14).

% Culminant: expert whose knowledge has no successor (depth ~6)
culminant(P,D) :- expert(P,D), no_apprentices(P,P).

% Regent: expert member of a headless order (depth ~6)
regent(X,O) :- member(X,O), no_head(O,O), expert(X,D).

% Devotee: sole-discipline scholar whose mentor is an expert in it (depth ~7)
devotee(P,D) :- sole_discipline(P,D), mentors(Q,P), expert(Q,D).

% Independent: unaffiliated expert (depth ~6)
independent(P,D) :- unaffiliated(P,P), expert(P,D).

% Vulnerable: seminal manuscript with only one surviving copy (depth ~8)
vulnerable(M,M) :- sole_copy(M,L), seminal(M,D).

% Purist: sole-discipline scholar in a sole-discipline lineage (depth ~7)
purist(P,D) :- sole_discipline(P,D), lineage(Q,P), sole_discipline(Q,D).

% Selfmade: expert with no patron and no order (depth ~6)
selfmade(P,P) :- expert(P,D), no_patron(P,P), unaffiliated(P,P).

% Maverick: expert whom nobody has endorsed (depth ~6)
maverick(P,D) :- expert(P,D), no_endorsers(P,P).

% Loyalist: delegate who belongs to only one order (depth ~5)
loyalist(P,O) :- delegate(P,O), sole_order(P,O).

% Orphan: unaffiliated, no patron, no apprentices (depth ~1)
orphan(P,P) :- unaffiliated(P,P), no_patron(P,P), no_apprentices(P,P).

% ────────────────────────────────────────────────────────────
%  SECTION 10 : GOVERNANCE & JURISDICTION  (depth 6-10)
% ────────────────────────────────────────────────────────────

% Jurisdiction: a head has jurisdiction over disciplines their order's experts study
jurisdiction(X,D) :- head(X,O), member(Y,O), expert(Y,D), X != Y.
jurisdiction(X,D) :- head(X,O), expert(X,D).

% Overlapping jurisdiction: two heads claim the same discipline
overlap(X,Y) :- jurisdiction(X,D), jurisdiction(Y,D), head(X,O1), head(Y,O2), O1 != O2, X != Y.

% Supreme: authoritative + jurisdiction + resides in a center (depth ~10)
supreme(P,D) :- authoritative(P,D), jurisdiction(P,D), resides(P,C), center(C,D).

% Mediator: luminary in a contested discipline, patron of both disputants (depth ~9)
mediator(P,D) :- luminary(P,D), dispute(X,Y), patron(P,X), patron(P,Y), contesteddisc(D,D).

% Arbiter: expert in a contested discipline, member of a third neutral order (depth ~8)
arbiter(P,D) :- expert(P,D), contesteddisc(D,D), dispute(X,Y), member(X,O1), member(Y,O2), member(P,O3), O3 != O1, O3 != O2.

% ────────────────────────────────────────────────────────────
%  SECTION 11 : APEX PREDICATES  (depth 8-14)
% ────────────────────────────────────────────────────────────
% These require combining information from multiple subsystems
% and traversing very long derivation chains.

% Grandmaster: supreme AND kingmaker (depth ~11)
grandmaster(P,P) :- supreme(P,D), kingmaker(P,P).

% Sage: supreme AND culminant (depth ~11)
sage(P,D) :- supreme(P,D), culminant(P,D).

% Archon: supreme, patron of a regent of a different order (depth ~12)
archon(P,P) :- supreme(P,D), head(P,O1), patron(P,Q), regent(Q,O2), O1 != O2.

% Paragon: luminary, polymath, AND founder of a prestigious library (depth ~10)
paragon(P,P) :- luminary(P,D), polymath(P,P), founded(P,L), prestigious(L,L).

% Last master: independent + culminant, residing in a center (depth ~10)
lastmaster(P,D) :- independent(P,D), culminant(P,D), resides(P,C), center(C,D).

% Custodian: last master who can access a vulnerable manuscript (depth ~12)
custodian(P,M) :- lastmaster(P,D), vulnerable(M,M), covers(M,D), canaccess(P,M).

% Guardian: custodian of a rare manuscript, in the manuscript's city (depth ~14)
guardian(P,M) :- custodian(P,M), rare(M,M), sole_copy(M,L), houses(L,C), resides(P,C).

% Peacemaker: mediator who is also an emissary of a third order (depth ~12)
peacemaker(P,D) :- mediator(P,D), emissary(P,O), dispute(X,Y), member(X,O1), member(Y,O2), O != O1, O != O2.

% Keystone: paragon AND arbiter (depth ~12)
keystone(P,P) :- paragon(P,P), arbiter(P,D).

% Eminence: grandmaster AND paragon (depth ~12)
eminence(P,P) :- grandmaster(P,P), paragon(P,P).

% ────────────────────────────────────────────────────────────
%  SECTION 12 : CROSS-SYSTEM INTERACTIONS  (depth 5-11)
% ────────────────────────────────────────────────────────────

% Bridge: endorsed by heads of two different orders (depth ~3)
bridge(X,X) :- endorsed(Y,X), endorsed(Z,X), head(Y,O1), head(Z,O2), O1 != O2, Y != Z.

% Promising: protege of a luminary, learned in the luminary's field (depth ~8)
promising(P,D) :- protege(P,X), luminary(X,D), learned(P,D).

% Operative: emissary stationed in a center of learning (depth ~9)
operative(X,D) :- emissary(X,O), resides(X,C), center(C,D).

% Power vacuum: headless order in an embattled state (depth ~10)
vacuum(O,O) :- no_head(O,O), embattled(O,O).

% Usurper: regent of a power-vacuum order who is a kingmaker (depth ~11)
usurper(P,O) :- regent(P,O), vacuum(O,O), kingmaker(P,P).

% Prodigy: promising scholar who is also a devotee (depth ~9)
prodigy(P,D) :- promising(P,D), devotee(P,D).

% ────────────────────────────────────────────────────────────
%  CONSTRAINTS
% ────────────────────────────────────────────────────────────

% Cannot be both allied and rival
:- alliance(X,Y), rivalry(X,Y).
:- allies(X,Y), rivals(X,Y).

% No self-alliances, self-rivalries, or self-roads
:- alliance(X,X).
:- rivalry(X,X).
:- road(X,X).

% A person heads at most one order
:- head(X,O1), head(X,O2), O1 != O2.

% An order has at most one head
:- head(X,O), head(Y,O), X != Y.

% A person resides in at most one city
:- resides(P,C1), resides(P,C2), C1 != C2.

% A library is housed in at most one city
:- houses(L,C1), houses(L,C2), C1 != C2.

% A person cannot mentor themselves
:- mentors(X,X).

% Mentorship has no 2-cycles
:- mentors(X,Y), mentors(Y,X).

% Negative fact consistency: no_apprentices means no mentees
:- no_apprentices(X,X), mentors(X,Y).

% sole_discipline means no second discipline
:- sole_discipline(P,D1), studies(P,D2), D1 != D2.

% sole_order means no second order
:- sole_order(P,O1), member(P,O2), O1 != O2.

% unaffiliated means no order membership
:- unaffiliated(P,P), member(P,O).

% no_head means no one heads that order
:- no_head(O,O), head(X,O).

% sole_copy means no second library holds it
:- sole_copy(M,L1), holds(L2,M), L1 != L2.

% no_patron means no one patronizes you
:- no_patron(P,P), patron(X,P).

% no_endorsers means no one endorses you
:- no_endorsers(P,P), endorsed(X,P).

% A polymath cannot have a sole discipline
:- polymath(P,P), sole_discipline(P,D).

% A crossorder member cannot have a sole order
:- crossorder(P,P), sole_order(P,O).

% An unaffiliated person cannot be a fellow, delegate, or head
:- unaffiliated(P,P), fellow(P,X).
:- unaffiliated(P,P), delegate(P,O).
:- unaffiliated(P,P), head(P,O).

% A selfmade scholar cannot be a luminary (no endorsers since unaffiliated)
:- selfmade(P,P), luminary(P,D).
