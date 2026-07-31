% ==========================================
% DOMAIN BASE FACTS
% ==========================================

% Nobles in the realm
noble(arthur).
noble(beatrice).
noble(cedric).
noble(diana).
noble(edward).
noble(fiona).
noble(george).
noble(helen).

% Geographical regions
region(north).
region(south).
region(east).
region(west).
region(capital).

% Family lineages
parent(arthur, cedric).
parent(arthur, diana).
parent(beatrice, cedric).
parent(beatrice, diana).

% Marriages
married(arthur, beatrice).
married(edward, fiona).

% The reigning monarch
monarch(george).

% Feudal hierarchy
vassal(arthur, george).
vassal(edward, george).
vassal(helen, george).

% Territorial governance
controls_region(arthur, north).
controls_region(edward, south).
controls_region(helen, east).
controls_region(george, capital).

% Military and wealth distributions
commands_army(arthur).
commands_army(helen).
wealthy(edward).
wealthy(george).

% Debts and secrets
owes_debt(cedric, edward).
owes_debt(diana, helen).
secret_lover(diana, edward).
secret_lover(fiona, cedric).
spy_for(fiona, helen).


% ==========================================
% DOMAIN RULES
% ==========================================

% 1. Family and Hierarchical Base Rules
sibling(X,Y) :- parent(Z,X), parent(Z,Y), X != Y.
liege(X,Y) :- vassal(Y,X).
married(X,Y) :- married(Y,X).
vassal(X,Y) :- noble(X), monarch(Y), X != Y.

% 2. Alliances and Loyalties
allied(X,Y) :- married(X,Y).
allied(X,Y) :- allied(Y,X).
allied(X,Y) :- vassal(X,Z), vassal(Y,Z), X != Y.
loyal(X,Y) :- vassal(X,Y), allied(X,Y).

% 3. Betrayal, Rebellion, and War
{loyal(X,Y), betrays(X,Y)} :- vassal(X,Y).
:- loyal(X,Y), betrays(X,Y).

rebel(X) :- betrays(X,Y), monarch(Y).
traitor(X) :- betrays(X,Y), allied(X,Y).
at_war(X,Y) :- rebel(X), monarch(Y).
at_war(X,Y) :- at_war(Y,X).
:- at_war(X,Y), allied(X,Y).

% 4. Rivalries and Support Networks
supports(X,Y) :- loyal(X,Y), at_war(Y,Z).
rival(X,Y) :- at_war(X,Z), supports(Y,Z), X != Y.
rival(X,Y) :- rival(Y,X).

% 5. Espionage, Secrets, and Blackmail
secret_lover(X,Y) :- secret_lover(Y,X).
{blackmails(X,Y), keeps_secret(X,Y)} :- secret_lover(Y,Z), spy_for(X,W), X != Y, X != Z.
:- blackmails(X,Y), keeps_secret(X,Y).
owes_debt(Y,X) :- blackmails(X,Y).

% 6. Economy, Tributes, and Penalties
wealthy(X) :- controls_region(X,Y), region(Y).
pays_tribute(X,Y) :- owes_debt(X,Y), wealthy(X).
pays_tribute(X,Y) :- vassal(X,Y).
{pays_tribute(X,Y), defaults(X,Y)} :- owes_debt(X,Y).
:- pays_tribute(X,Y), defaults(X,Y).

% 7. Justice, Imprisonment, and Escape
imprisoned(X) :- defaults(X,Y), liege(Y,X).
imprisoned(X) :- traitor(X), captured(X).
{captured(X), escaped(X)} :- rebel(X).
:- captured(X), escaped(X).

% 8. Safe Havens and Exile
fled_to(X,Y) :- escaped(X), region(Y), controls_region(Z,Y), rival(Z,W), monarch(W).
safe_haven(Y,X) :- fled_to(X,Y).
safe_haven(Y,X) :- region(Y), allied(Z,X), controls_region(Z,Y).
exiled(X) :- traitor(X), alive(X).
:- exiled(X), controls_region(X,Y).

% 9. Territorial Claims and Disputes
claims_region(X,Y) :- monarch(X), region(Y).
claims_region(X,Y) :- controls_region(X,Y).
at_war(X,Y) :- claims_region(X,Z), claims_region(Y,Z), X != Y.

% 10. Assassinations, Guards, and Survival
assassin(X) :- spy_for(X,Y), at_war(Y,Z).
target(Z) :- assassin(X), spy_for(X,Y), at_war(Y,Z).
guard(X,Y) :- loyal(X,Y), target(Y).
{dead(X), alive(X)} :- target(X).
:- dead(X), alive(X).
alive(X) :- target(X), guard(Z,X), victor(Z,W), assassin(W).
traitor(X) :- assassin(X), target(Y), liege(Y,X).

% 11. Royal Succession and Legitimacy
heir(X,Y) :- parent(Y,X), alive(X).
heir(X,Y) :- sibling(X,Z), heir(Z,Y), dead(Z).
legitimate_claim(X) :- heir(X,Y), monarch(Y).
legitimate_claim(X) :- heir(X,Y), legitimate_claim(Y).
usurper(X) :- monarch(X), dead(Y), legitimate_claim(Y).
:- usurper(X), legitimate_claim(X).

% 12. Duels, Heroes, and Cowards
commands_army(X) :- monarch(X).
commands_army(X) :- noble(X), wealthy(X).
{duel(X,Y), cowardly_flees(X,Y)} :- rival(X,Y), commands_army(X), commands_army(Y).
:- duel(X,Y), cowardly_flees(X,Y).

{victor(X,Y), victor(Y,X)} :- duel(X,Y).
:- victor(X,Y), victor(Y,X).
dead(X) :- duel(Y,X), victor(Y,X).

hero(X) :- victor(X,Y), duel(X,Y).
hero(X) :- captured(Y), traitor(Y), loyal(X,Z), monarch(Z).

coward(X) :- cowardly_flees(X,Y).
coward(X) :- escaped(X), betrays(X,Y), allied(X,Y).
