% ============================================================
% RULE BASE: The Kingdom of Valdris — Feudal Politics & Society
% ============================================================
% Domain: A medieval feudal kingdom with nobles, knights,
%   territories, resources, and layered political, military,
%   social, and diplomatic relationships. The rule base is
%   designed to pose challenging multi-hop reasoning tasks
%   involving feudal hierarchy, inheritance, loyalty, alliance,
%   resource control, succession, and conflict resolution.
% ============================================================

% --- BASE FACTS ---

% --- Gender ---
male(arthur).  male(cador).   male(edric).  male(gareth).
male(ivan).    male(jasper).  male(lorn).   male(oswin).
female(beryl). female(dwyn).  female(fiona).female(hilda).
female(keira). female(mira).

% --- Marriages (bidirectional in base facts) ---
married(arthur, beryl). married(beryl, arthur).
married(cador, dwyn).   married(dwyn, cador).
married(gareth, keira). married(keira, gareth).

% --- Parent-child relationships ---
parent(arthur, gareth). parent(beryl, gareth).
parent(arthur, hilda).  parent(beryl, hilda).
parent(cador, ivan).    parent(dwyn, ivan).
parent(edric, jasper).  parent(edric, keira).
parent(gareth, mira).   parent(keira, mira).
parent(gareth, oswin).  parent(keira, oswin).
parent(fiona, lorn).

% --- Base noble status ---
noble(arthur). noble(cador). noble(edric). noble(fiona).

% --- Base knights ---
knight(arthur). knight(cador). knight(gareth). knight(edric).

% --- Territory holdings ---
holds(arthur, crownlands).
holds(cador,  northmoor).
holds(edric,  eastridge).
holds(gareth, southfen).
holds(lorn,   westholm).
holds(hilda,  darkwood).

% --- Sworn allegiance (basis of the feudal bond) ---
sworn(cador,  arthur).
sworn(edric,  arthur).
sworn(gareth, cador).
sworn(lorn,   edric).
sworn(hilda,  arthur).

% --- Territory adjacency (bidirectional) ---
borders(northmoor,  crownlands). borders(crownlands, northmoor).
borders(northmoor,  eastridge).  borders(eastridge,  northmoor).
borders(southfen,   crownlands). borders(crownlands, southfen).
borders(southfen,   westholm).   borders(westholm,   southfen).
borders(eastridge,  crownlands). borders(crownlands, eastridge).
borders(westholm,   darkwood).   borders(darkwood,   westholm).
borders(darkwood,   crownlands). borders(crownlands, darkwood).

% --- Resource production ---
produces(northmoor,  iron).
produces(northmoor,  timber).
produces(southfen,   grain).
produces(eastridge,  silver).
produces(westholm,   grain).
produces(crownlands, stone).
produces(darkwood,   timber).

% --- Training relationships ---
trained_by(gareth, cador).
trained_by(ivan,   cador).
trained_by(jasper, gareth).
trained_by(lorn,   edric).
trained_by(hilda,  arthur).
trained_by(oswin,  gareth).
trained_by(keira,  fiona).

% --- Historical conflicts (symmetric) ---
conflict(cador,  edric).  conflict(edric,  cador).
conflict(hilda,  lorn).   conflict(lorn,   hilda).
conflict(ivan,   jasper). conflict(jasper, ivan).

% --- Base trust ---
trusts(arthur, beryl).  trusts(beryl, arthur).
trusts(cador,  dwyn).   trusts(dwyn,  cador).
trusts(gareth, keira).  trusts(keira, gareth).
trusts(arthur, cador).
trusts(edric,  jasper).
trusts(fiona,  lorn).

% --- Base political support ---
supports(arthur, gareth).
supports(cador,  ivan).
supports(edric,  jasper).

% --- Betrothal (bidirectional) ---
betrothed(ivan, mira). betrothed(mira, ivan).


% ============================================================
% --- DERIVED RULES ---
% ============================================================

% == SECTION 1: LINEAGE & FAMILY ==

% Rule 1: Every parent is an ancestor.
ancestor(X,Y) :- parent(X,Y).

% Rule 2: Ancestry is transitive.
ancestor(X,Z) :- parent(X,Y), ancestor(Y,Z).

% Rule 3: Descent is the inverse of ancestry.
descends(Y,X) :- ancestor(X,Y).

% Rule 4: Noble status propagates through any noble ancestor.
noble(X) :- descends(X,Y), noble(Y).

% Rule 5: Two different persons sharing a common parent are siblings.
sibling(X,Y) :- parent(Z,X), parent(Z,Y), X != Y.

% Rule 6: Children of siblings are cousins.
cousin(X,Y) :- parent(A,X), parent(B,Y), sibling(A,B), X != Y.

% Rule 7: Marrying someone makes you an in-law of that person's parents.
in_law(X,Z) :- married(X,Y), parent(Z,Y).

% Rule 8: Marrying a noble grants noble status.
noble(Y) :- married(Y,X), noble(X).

% Rule 9: A knight who governs a territory is recognized as noble.
noble(X) :- knight(X), holds(X,T).


% == SECTION 2: FEUDAL HIERARCHY ==

% Rule 10: Sworn allegiance establishes a vassal relationship.
vassal(X,Y) :- sworn(X,Y).

% Rule 11: Vassalage implies lordship (inverse relation).
lord(Y,X) :- vassal(X,Y).

% Rule 12: A lord of a lord is a liege.
liege(X,Z) :- lord(X,Y), lord(Y,Z).

% Rule 13: A direct vassal is a subject of their lord.
subject(X,Y) :- vassal(X,Y).

% Rule 14: An indirect subordinate under a liege is also a subject.
subject(X,Y) :- liege(Y,X).

% Rule 15: Sworn allegiance creates personal loyalty.
loyal(X,Y) :- sworn(X,Y).

% Rule 16: A vassal who also trusts their lord is deeply loyal.
loyal(X,Y) :- trusts(X,Y), vassal(X,Y).

% Rule 17: Loyal persons support those they are loyal to.
supports(X,Y) :- loyal(X,Y).

% Rule 18: Subjects extend trust to their overlords (feudal expectation).
trusts(X,Y) :- subject(X,Y).


% == SECTION 3: MILITARY & KNIGHTHOOD ==

% Rule 19: A lord militarily commands their direct vassal.
commands(X,Y) :- lord(X,Y).

% Rule 20: The command relation is transitive.
commands(X,Z) :- commands(X,Y), commands(Y,Z).

% Rule 21: A male trainee of a knight becomes a knight.
knight(X) :- trained_by(X,Y), knight(Y), male(X).

% Rule 22: A female trainee of a knight may become a knight (choice).
{knight(X)} :- trained_by(X,Y), knight(Y), female(X).

% Rule 23: A knight commands those they personally trained.
commands(X,Y) :- knight(X), trained_by(Y,X).

% Rule 24: A noble knight commands all those who are their subjects.
commands(X,Y) :- noble(X), knight(X), subject(Y,X).


% == SECTION 4: TERRITORY & RESOURCE CONTROL ==

% Rule 25: Holding a territory grants direct control over its resources.
controls(X,R) :- holds(X,T), produces(T,R).

% Rule 26: A lord controls the resources produced in a vassal's territory.
controls(X,R) :- lord(X,Y), holds(Y,T), produces(T,R).

% Rule 27: A liege controls resources produced in all indirect subjects' territories.
controls(X,R) :- liege(X,Y), holds(Y,T), produces(T,R).


% == SECTION 5: DIPLOMACY — ALLIANCES & ENMITY ==

% Rule 28: Historical conflict creates enmity.
enemy(X,Y) :- conflict(X,Y).

% Rule 29: Enmity is symmetric.
enemy(Y,X) :- enemy(X,Y).

% Rule 30: The enemy of one's enemy may become an ally (choice).
{ally(X,Z)} :- enemy(X,Y), enemy(Y,Z), X != Z.

% Rule 31: An ally of one's ally may also become an ally (choice).
{ally(X,Z)} :- ally(X,Y), ally(Y,Z), X != Z.

% Rule 32: Alliance is symmetric.
ally(Y,X) :- ally(X,Y).

% Rule 33: Noble cousins may form a dynastic alliance (choice).
{ally(X,Y)} :- cousin(X,Y), noble(X), noble(Y).

% Rule 34: Trading partners who trust each other may become allies (choice).
{ally(X,Y)} :- trades(X,Y), trusts(X,Y).

% Rule 35: Parents of betrothed children may form a political alliance (choice).
{ally(X,Y)} :- parent(X,A), parent(Y,B), betrothed(A,B), X != Y.

% Rule 36: Nobles who both support the same lord may ally (choice).
{ally(X,Y)} :- supports(X,Z), supports(Y,Z), noble(X), noble(Y), X != Y.

% Rule 37: One's ally's enemy may become one's own enemy (choice).
{enemy(X,Z)} :- ally(X,Y), enemy(Y,Z), X != Z.

% Constraint 1: A pair cannot be simultaneously allied and hostile.
:- ally(X,Y), enemy(X,Y).


% == SECTION 6: TRADE ==

% Rule 38: Adjacent territory holders who are not enemies can trade.
trades(X,Y) :- holds(X,T1), holds(Y,T2), borders(T1,T2), not enemy(X,Y), X != Y.

% Rule 39: Allied territory holders sharing a border engage in active trade.
trades(X,Y) :- ally(X,Y), holds(X,T1), holds(Y,T2), borders(T1,T2).

% Rule 40: Persons who control the same resource may trade if not enemies.
trades(X,Y) :- controls(X,R), controls(Y,R), not enemy(X,Y), X != Y.


% == SECTION 7: TRUST ==

% Rule 41: Vassals trust their lords.
trusts(X,Y) :- vassal(X,Y).

% Rule 42: Trainees trust their trainers.
trusts(X,Y) :- trained_by(X,Y).

% Rule 43: Married partners trust each other.
trusts(X,Y) :- married(X,Y).

% Rule 44: In-laws extend trust to one another.
trusts(X,Y) :- in_law(X,Y).

% Rule 45: Trust may propagate transitively through chains of trust (choice).
{trusts(X,Z)} :- trusts(X,Y), trusts(Y,Z), X != Z.

% Constraint 2: One cannot trust an enemy.
:- trusts(X,Y), enemy(X,Y).


% == SECTION 8: PROTECTION ==

% Rule 46: A lord is duty-bound to protect their vassal.
protects(X,Y) :- lord(X,Y).

% Rule 47: A parent protects their child.
protects(X,Y) :- parent(X,Y).

% Rule 48: Married partners protect each other.
protects(X,Y) :- married(X,Y).

% Rule 49: Allies protect each other.
protects(X,Y) :- ally(X,Y).

% Rule 50: One who commands another is also responsible for protecting them.
protects(X,Y) :- commands(X,Y).


% == SECTION 9: SUPPORT ==

% Rule 51: A lord supports their vassal.
supports(X,Y) :- lord(X,Y).

% Rule 52: A parent supports their child.
supports(X,Y) :- parent(X,Y).

% Rule 53: Allies support each other.
supports(X,Y) :- ally(X,Y).

% Constraint 3: One cannot support an enemy.
:- supports(X,Y), enemy(X,Y).


% == SECTION 10: SUCCESSION & TERRITORIAL CLAIMS ==

% Rule 54: A male child of a territory holder is an heir to that territory.
heir(Y,T) :- holds(X,T), parent(X,Y), male(Y).

% Rule 55: A female child of a territory holder may be an heir (choice).
{heir(Y,T)} :- holds(X,T), parent(X,Y), female(Y).

% Rule 56: The betrothed of an heir may also claim heirship (choice).
{heir(X,T)} :- betrothed(X,Y), heir(Y,T).

% Rule 57: Being an heir to a territory generates a formal dynastic claim.
claims(X,T) :- heir(X,T).

% Rule 58: Descent from a current territory holder creates a dynastic claim.
claims(X,T) :- descends(X,Y), holds(Y,T), X != Y.

% Rule 59: A claim on a territory constitutes a threat against its current holder.
threatens(X,Z) :- claims(X,T), holds(Z,T), X != Z.

% Rule 60: Bordering parties who share a conflict history threaten each other's holdings.
threatens(X,Y) :- conflict(X,Y), holds(X,T1), holds(Y,T2), borders(T1,T2).


% == SECTION 11: PEACE ==

% Rule 61: Non-adjacent, non-enemy territory holders are at peace.
peace(X,Y) :- holds(X,T1), holds(Y,T2), not borders(T1,T2), not enemy(X,Y), X != Y.

% Rule 62: Allies are at peace with each other.
peace(X,Y) :- ally(X,Y).


% == SECTION 12: INTEGRITY CONSTRAINTS ==

% Constraint 4: Peace and an active threat cannot coexist between the same pair.
:- peace(X,Y), threatens(X,Y).

% Constraint 5: One cannot threaten someone one is bound to protect.
:- threatens(X,Y), protects(X,Y).

% Constraint 6: Vassalage cannot be circular (no two parties can be each other's vassal).
:- vassal(X,Y), vassal(Y,X).

% Constraint 7: Siblings cannot be married to each other.
:- married(X,Y), sibling(X,Y).

% Constraint 8: Ancestry cannot be cyclic.
:- ancestor(X,X).

% Constraint 9: Two heirs to the same territory cannot be enemies with each other.
:- heir(X,T), heir(Y,T), enemy(X,Y), X != Y.

% Constraint 10: No person can issue commands to themselves.
:- commands(X,X).
