% ============================================================
% RULE BASE: The Grand Academy of Veranthos — Arcane Scholars
% ============================================================
% Domain: A magical academy composed of towers, each
%   specialising in one or more arcane disciplines. Scholars
%   study, master, and teach disciplines, hold and discover
%   magical artifacts, form mentorship bonds, rivalries,
%   alliances, endorsements, and censures. The rule base
%   captures multi-hop reasoning across knowledge hierarchies,
%   artifact custody, scholastic politics, and influence
%   propagation across the academy's social structure.
% ============================================================

% --- BASE FACTS ---

% --- Scholars ---
scholar(aldus).  scholar(bram).   scholar(celia).
scholar(dorn).   scholar(evia).   scholar(falon).
scholar(gwen).   scholar(holt).   scholar(iris).
scholar(joran).

% --- Towers within the academy ---
tower(silver_tower).   tower(obsidian_tower).
tower(amber_tower).    tower(ivory_tower).

% --- Tower primary and secondary discipline focus ---
tower_focus(silver_tower,   astromancy).
tower_focus(silver_tower,   divination).
tower_focus(obsidian_tower, runecraft).
tower_focus(obsidian_tower, enchantment).
tower_focus(amber_tower,    alchemy).
tower_focus(amber_tower,    transmutation).
tower_focus(ivory_tower,    enchantment).
tower_focus(ivory_tower,    divination).

% --- Membership of scholars in towers ---
belongs(aldus, silver_tower).    belongs(evia,  silver_tower).
belongs(iris,  silver_tower).    belongs(bram,  obsidian_tower).
belongs(dorn,  obsidian_tower).  belongs(joran, obsidian_tower).
belongs(celia, amber_tower).     belongs(gwen,  amber_tower).
belongs(falon, ivory_tower).     belongs(holt,  ivory_tower).

% --- Mentorship (X mentors Y) ---
mentor(aldus, evia).
mentor(aldus, iris).
mentor(bram,  dorn).
mentor(bram,  joran).
mentor(celia, gwen).
mentor(falon, holt).
mentor(falon, gwen).   % cross-tower mentorship

% --- Studies (base enrolment in disciplines) ---
studies(aldus, astromancy).  studies(aldus, divination).
studies(bram,  runecraft).   studies(bram,  enchantment).
studies(celia, alchemy).     studies(celia, transmutation).
studies(dorn,  runecraft).
studies(evia,  astromancy).
studies(falon, enchantment). studies(falon, divination).
studies(gwen,  alchemy).     studies(gwen,  transmutation).
studies(holt,  enchantment).
studies(iris,  astromancy).  studies(iris,  divination).
studies(joran, runecraft).   studies(joran, alchemy).

% --- Established mastery ---
masters(aldus, astromancy).
masters(bram,  runecraft).
masters(celia, alchemy).
masters(falon, enchantment).

% --- Artifacts ---
artifact(staff_veranthos).  artifact(orb_sight).
artifact(rune_blade).       artifact(alembic_prime).
artifact(star_lens).        artifact(codex_arcanum).
artifact(veil_stone).       artifact(ember_ring).

% --- Artifact disciplinary type ---
artifact_type(staff_veranthos, astromancy).
artifact_type(orb_sight,       divination).
artifact_type(rune_blade,      runecraft).
artifact_type(alembic_prime,   alchemy).
artifact_type(star_lens,       astromancy).
artifact_type(codex_arcanum,   enchantment).
artifact_type(veil_stone,      divination).
artifact_type(ember_ring,      transmutation).

% --- Artifact holders ---
holds_artifact(aldus, staff_veranthos).
holds_artifact(aldus, star_lens).
holds_artifact(bram,  rune_blade).
holds_artifact(celia, alembic_prime).
holds_artifact(falon, codex_arcanum).
holds_artifact(evia,  orb_sight).
holds_artifact(gwen,  ember_ring).
holds_artifact(holt,  veil_stone).

% --- Artifact discoverers ---
discovered(aldus, staff_veranthos).
discovered(bram,  rune_blade).
discovered(celia, alembic_prime).
discovered(evia,  orb_sight).
discovered(iris,  star_lens).    % iris found star_lens; aldus now holds it
discovered(joran, veil_stone).   % joran found veil_stone; holt now holds it
discovered(gwen,  ember_ring).

% --- Compatible disciplines (synergistic cross-study) ---
compatible(astromancy,    divination).
compatible(divination,    astromancy).
compatible(alchemy,       transmutation).
compatible(transmutation, alchemy).
compatible(runecraft,     enchantment).
compatible(enchantment,   runecraft).

% --- Antagonistic disciplines (interfering cross-study) ---
antagonistic(astromancy,    runecraft).
antagonistic(runecraft,     astromancy).
antagonistic(alchemy,       divination).
antagonistic(divination,    alchemy).
antagonistic(transmutation, enchantment).
antagonistic(enchantment,   transmutation).

% --- Base rivalries ---
rival(bram,  celia).  rival(celia, bram).
rival(dorn,  holt).   rival(holt,  dorn).
rival(iris,  joran).  rival(joran, iris).
rival(falon, aldus).  rival(aldus, falon).

% --- Base endorsements ---
endorses(aldus, evia).
endorses(aldus, iris).
endorses(celia, gwen).
endorses(falon, holt).
endorses(bram,  joran).

% --- Base trust ---
trusts(aldus, evia).   trusts(evia,  aldus).
trusts(bram,  dorn).   trusts(celia, gwen).
trusts(falon, holt).   trusts(iris,  evia).

% --- Base censure ---
censures(bram, iris).   % cross-tower disciplinary censure

% --- Base seniority ---
senior_to(aldus, evia).   senior_to(aldus, iris).
senior_to(bram,  dorn).   senior_to(bram,  joran).
senior_to(celia, gwen).   senior_to(falon, holt).
senior_to(falon, gwen).

% ============================================================
% --- DERIVED RULES ---
% ============================================================

% == SECTION 1: MENTORSHIP & PROTEGE ==

% Rule 1: A mentee is formally the protege of their mentor.
protege(Y,X) :- mentor(X,Y).

% Rule 2: A mentor automatically endorses their mentee.
endorses(X,Y) :- mentor(X,Y).

% Rule 3: A mentee extends trust to their mentor.
trusts(Y,X) :- mentor(X,Y).

% Rule 4: A mentor is senior to their mentee.
senior_to(X,Y) :- mentor(X,Y).

% Rule 5: A mentor directly oversees their mentee.
oversees(X,Y) :- mentor(X,Y).

% Rule 6: Seniority is transitive across the academy hierarchy.
senior_to(X,Z) :- senior_to(X,Y), senior_to(Y,Z).

% Rule 7: Oversight implies seniority.
senior_to(X,Y) :- oversees(X,Y).

% Rule 8: Fellow proteges of the same mentor extend trust to each other.
trusts(X,Y) :- protege(X,Z), protege(Y,Z), not rival(X,Y), X != Y.


% == SECTION 2: TEACHING & STUDY ==

% Rule 9: A mentor teaches their mentee in any discipline they have mastered
%         that the mentee is also currently studying.
teaches(X,Y) :- mentor(X,Y), masters(X,D), studies(Y,D).

% Rule 10: A scholar who is taught by another in a discipline may expand
%          into a compatible discipline (the exposure opens new paths).
{studies(Y,D2)} :- teaches(X,Y), studies(X,D1), compatible(D1,D2).

% Rule 11: Studying one discipline may organically draw a scholar
%          toward its compatible counterpart.
{studies(X,D2)} :- studies(X,D1), compatible(D1,D2).

% Rule 12: A qualified scholar may teach any fellow tower-member
%          who is enrolled in that same discipline.
teaches(X,Y) :- qualified(X,D), studies(Y,D),
                belongs(X,T), belongs(Y,T), X != Y.

% Rule 13: A teacher influences those they teach.
influences(X,Y) :- teaches(X,Y).


% == SECTION 3: QUALIFICATION & MASTERY ==

% Rule 14: Mastery in a discipline always implies qualification in it.
qualified(X,D) :- masters(X,D).

% Rule 15: A scholar endorsed by a master of a discipline, who also
%          studies it, may become qualified in that discipline.
{qualified(X,D)} :- studies(X,D), endorses(Y,X), masters(Y,D).

% Rule 16: A scholar qualified in two compatible disciplines is a specialist.
specialist(X) :- qualified(X,D1), qualified(X,D2),
                 compatible(D1,D2), D1 != D2.

% Rule 17: A scholar who studies a discipline, belongs to a tower that
%          focuses on it, and is endorsed by a master of it may attain mastery.
{masters(X,D)} :- studies(X,D), belongs(X,T), tower_focus(T,D),
                  endorses(Y,X), masters(Y,D), senior_to(Y,X).


% == SECTION 4: ARTIFACTS & ACCESS ==

% Rule 18: A discoverer of an artifact retains permanent access to it.
accesses(X,A) :- discovered(X,A).

% Rule 19: Holding an artifact grants access to it.
accesses(X,A) :- holds_artifact(X,A).

% Rule 20: A master of the relevant discipline who belongs to the
%          tower that focuses on that discipline may access related artifacts.
accesses(X,A) :- masters(X,D), artifact_type(A,D),
                 belongs(X,T), tower_focus(T,D).

% Rule 21: A scholar who accesses an artifact they discovered
%          influences all their direct mentees through shared lore.
influences(X,Y) :- accesses(X,A), discovered(X,A), mentor(X,Y).

% Rule 22: When a scholar holds an artifact they did not discover,
%          and the discoverer has not endorsed them, the discoverer
%          may suspect misappropriation.
{suspects(Z,X)} :- holds_artifact(X,A), discovered(Z,A),
                   Z != X, not endorses(Z,X).

% Rule 23: An artifact is contested when two rivals can both access it.
contested(A) :- accesses(X,A), accesses(Y,A), rival(X,Y), X != Y.

% Rule 24: The discoverer of a contested artifact may denounce
%          whoever holds it without their sanction.
{denounces(X,Y)} :- contested(A), discovered(X,A),
                    holds_artifact(Y,A), X != Y.

% Rule 25: Tower-mates who both access the same artifact develop
%          a knowledge link through shared study of that object.
{knowledge_link(X,Y)} :- accesses(X,A), accesses(Y,A),
                          belongs(X,T), belongs(Y,T), X != Y.


% == SECTION 5: COLLABORATION & KNOWLEDGE ==

% Rule 26: Scholars in the same tower may choose to collaborate.
{collaborates(X,Y)} :- belongs(X,T), belongs(Y,T), X != Y.

% Rule 27: Scholars studying compatible disciplines across any tower
%          may choose to collaborate.
{collaborates(X,Y)} :- studies(X,D1), studies(Y,D2),
                        compatible(D1,D2), X != Y.

% Rule 28: Collaboration generates mutual trust.
trusts(X,Y) :- collaborates(X,Y).
trusts(Y,X) :- collaborates(X,Y).

% Rule 29: Collaborating scholars generate a mutual knowledge link.
knowledge_link(X,Y) :- collaborates(X,Y).
knowledge_link(Y,X) :- collaborates(X,Y).

% Rule 30: Two scholars with a mutual knowledge link who are not rivals
%          may choose to formalise collaboration.
{collaborates(X,Y)} :- knowledge_link(X,Y), knowledge_link(Y,X),
                        not rival(X,Y), X != Y.

% Rule 31: When the same scholar influences two different peers,
%          those peers acquire a knowledge link to each other.
knowledge_link(Y,Z) :- influences(X,Y), influences(X,Z), X != Y, Y != Z.

% Rule 32: Proteges of the same mentor share a knowledge link
%          through their common scholarly lineage.
{knowledge_link(X,Y)} :- protege(X,Z), protege(Y,Z), X != Y.


% == SECTION 6: RIVALRY & CONFLICT ==

% Rule 33: Scholars in different towers who study antagonistic
%          disciplines may become rivals.
{rival(X,Y)} :- studies(X,D1), studies(Y,D2), antagonistic(D1,D2),
                belongs(X,T1), belongs(Y,T2), T1 != T2, X != Y.

% Rule 34: Rivals may denounce each other.
{denounces(X,Y)} :- rival(X,Y).

% Rule 35: A denouncement leads directly to suspicion.
suspects(X,Y) :- denounces(X,Y).

% Rule 36: When rivals can both access the same artifact, one may
%          move to formally censure the other.
{censures(X,Y)} :- rival(X,Y), accesses(X,A), accesses(Y,A), X != Y.

% Rule 37: When a mentor censures their own mentee, the mentorship
%          bond may fracture and produce a rivalry.
{rival(X,Y)} :- censures(Y,X), mentor(Y,X).


% == SECTION 7: ENDORSEMENT, CENSURE & TRUST ==

% Rule 38: Endorsing another scholar is an act of influence over them.
influences(X,Y) :- endorses(X,Y).

% Rule 39: A senior scholar who censures a junior causes that junior
%          to come under collective suspicion.
suspects(Y,X) :- censures(Y,X), senior_to(Y,X).

% Rule 40: A scholar who is endorsed by a senior and has achieved mastery
%          may be elevated within the academy.
{elevated(X)} :- endorses(Y,X), masters(X,D), senior_to(Y,X).

% Rule 41: Influence propagates along the mentorship chain.
influences(X,Z) :- influences(X,Y), mentor(Y,Z).

% Rule 42: Trust may propagate transitively through established bonds.
{trusts(X,Z)} :- trusts(X,Y), trusts(Y,Z), X != Z.


% == SECTION 8: TOWER HIERARCHY ==

% Rule 43: A scholar who has mastered their tower's focus discipline
%          oversees all tower-mates who have not yet mastered it.
oversees(X,Y) :- masters(X,D), tower_focus(T,D), belongs(X,T),
                 belongs(Y,T), not masters(Y,D), X != Y.

% Rule 44: An overseer may choose to endorse scholars under their oversight.
{endorses(X,Y)} :- oversees(X,Y), belongs(X,T), belongs(Y,T).

% Rule 45: An elevated scholar oversees all non-elevated scholars
%          within their own tower.
oversees(X,Y) :- elevated(X), belongs(X,T), belongs(Y,T),
                 not elevated(Y), X != Y.


% == SECTION 9: ELEVATION & INFLUENCE ==

% Rule 46: A specialist who has been elevated becomes a figure of
%          broad influence over all members of their tower.
influences(X,Y) :- elevated(X), specialist(X),
                   belongs(X,T), belongs(Y,T), X != Y.

% Rule 47: An elevated scholar who also holds an artifact of their
%          tower's discipline is recognised as a tower authority,
%          and influences scholars across compatible towers.
influences(X,Y) :- elevated(X), holds_artifact(X,A),
                   artifact_type(A,D), tower_focus(T1,D), belongs(X,T1),
                   tower_focus(T2,D), belongs(Y,T2), T1 != T2, X != Y.

% Rule 48: A scholar influenced by an elevated colleague may have
%          their own studies deepened toward mastery (choice).
{masters(X,D)} :- influences(Y,X), elevated(Y), studies(X,D),
                  masters(Y,D), belongs(X,T), tower_focus(T,D).


% == SECTION 10: INTEGRITY CONSTRAINTS ==

% Constraint 1: A scholar cannot simultaneously trust and suspect
%               the same person.
:- trusts(X,Y), suspects(X,Y).

% Constraint 2: A scholar cannot both endorse and censure the same person.
:- endorses(X,Y), censures(X,Y).

% Constraint 3: Rivals cannot collaborate.
:- collaborates(X,Y), rival(X,Y).

% Constraint 4: No scholar may study two antagonistic disciplines
%               at the same time.
:- studies(X,D1), studies(X,D2), antagonistic(D1,D2).

% Constraint 5: Seniority cannot be circular.
:- senior_to(X,X).

% Constraint 6: One who suspects another cannot endorse them.
:- suspects(X,Y), endorses(X,Y).

% Constraint 7: Scholars studying antagonistic disciplines cannot
%               be listed as collaborators.
:- collaborates(X,Y), studies(X,D1), studies(Y,D2), antagonistic(D1,D2).

% Constraint 8: An artifact held by the same person who discovered it
%               cannot be considered contested on those grounds alone.
:- contested(A), holds_artifact(X,A), discovered(X,A),
   not accesses(Y,A), rival(X,Y).
