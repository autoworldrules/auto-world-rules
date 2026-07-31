% ============================================================
% Domain: Medieval Kingdom — Feudal Politics, Warfare & Diplomacy
% ============================================================

% --- Symmetry rules ---
borders(Y,X) :- borders(X,Y).
married_to(Y,X) :- married_to(X,Y).
trades_with(Y,X) :- trades_with(X,Y).
at_war(H2,H1) :- at_war(H1,H2).

% --- Same house membership ---
same_house(X,Y) :- house_of(X,H), house_of(Y,H), X != Y.

% --- Alliance formation ---
allied_with(X,Y) :- same_house(X,Y).
allied_with(X,Z) :- married_to(X,Y), house_of(Y,H), house_of(Z,H), X != Z, not enemy_of(X,Z).
allied_with(Y,X) :- allied_with(X,Y).
allied_with(X,Z) :- allied_with(X,Y), same_house(Y,Z), X != Z, not enemy_of(X,Z).

% --- Enmity ---
enemy_of(X,Y) :- noble(X), noble(Y), house_of(X,H1), house_of(Y,H2), at_war(H1,H2).
enemy_of(Y,X) :- enemy_of(X,Y).

% --- Overlordship ---
overlord_of(X,Y) :- vassal_of(Y,X).
overlord_of(X,Z) :- overlord_of(X,Y), vassal_of(Z,Y).

% --- Territorial domain ---
domain(X,T) :- controls(X,T).
domain(X,T) :- overlord_of(X,Y), controls(Y,T).

% --- Neighbor lords ---
neighbor_lord(X,Y) :- controls(X,T1), controls(Y,T2), borders(T1,T2), X != Y.

% --- Diplomatic ties ---
diplomatic_tie(X,Y) :- controls(X,T1), controls(Y,T2), trades_with(T1,T2), X != Y.
diplomatic_tie(X,Y) :- allied_with(X,Y), neighbor_lord(X,Y).
diplomatic_tie(Y,X) :- diplomatic_tie(X,Y).

% --- Power ---
powerful(X) :- overlord_of(X,Y).
powerful(X) :- domain(X,T1), domain(X,T2), T1 != T2.

% --- Rivalry ---
rival_of(X,Y) :- neighbor_lord(X,Y), house_of(X,H1), house_of(Y,H2), H1 != H2, not allied_with(X,Y).
rival_of(X,Y) :- claims(X,T), claims(Y,T), X != Y.
rival_of(X,Y) :- blocked_trade(T1,T2), controls(X,T1), controls(Y,T2), X != Y.

% --- Influence ---
influences(X,Y) :- overlord_of(X,Y).
influences(X,Y) :- diplomatic_tie(X,Y), powerful(X), not powerful(Y).
influences(X,Y) :- married_to(X,Z), overlord_of(Z,Y), X != Y.

% --- Threats ---
threatens(X,Y) :- enemy_of(X,Y), neighbor_lord(X,Y).
threatens(X,Y) :- rival_of(X,Y), powerful(X), not powerful(Y).
threatens(X,Y) :- kingmaker(Y), enemy_of(X,Z), allied_with(Y,Z), neighbor_lord(X,Y).

% --- Protection ---
protects(X,Y) :- allied_with(X,Y), neighbor_lord(X,Y).
protects(X,Y) :- overlord_of(X,Y).
protects(X,Z) :- loyal_to(X,Y), protects(Y,Z), X != Z.

% --- Vulnerability ---
has_protector(X) :- protects(Y,X).
vulnerable(X) :- threatens(Y,X), not has_protector(X).
vulnerable(X) :- enemy_of(X,Y), powerful(Y), not powerful(X), neighbor_lord(X,Y).
vulnerable(X) :- suspect(X), enemy_of(X,Y).

% --- Claims ---
claims(X,T) :- heir_of(X,Y), controls(Y,T).
claims(X,T) :- enemy_of(X,Y), controls(Y,T), controls(X,T2), borders(T,T2).
claims(X,T) :- rival_of(X,Y), vulnerable(Y), controls(Y,T).

% --- Contested territory ---
contested(T) :- claims(X,T), claims(Y,T), X != Y.
contested(T) :- controls(X,T), threatens(Y,X).

% --- Blocked trade ---
blocked_trade(T1,T2) :- trades_with(T1,T2), controls(X,T1), controls(Y,T2), enemy_of(X,Y).
blocked_trade(T1,T2) :- trades_with(T1,T2), contested(T1).
blocked_trade(Y,X) :- blocked_trade(X,Y).

% --- Loyalty ---
loyal_to(X,Y) :- vassal_of(X,Y), not betrays(X,Y).
loyal_to(X,Y) :- same_house(X,Y), not rival_of(X,Y).
loyal_to(X,Y) :- influences(Y,X), same_house(X,Y).

% --- Betrayal (choice rules) ---
{betrays(X,Y)} :- vassal_of(X,Y), allied_with(X,Z), enemy_of(Y,Z).
{betrays(X,Y)} :- vassal_of(X,Y), married_to(X,Z), enemy_of(Z,Y).

% --- Traitors and suspects ---
traitor(X) :- betrays(X,Y).
suspect(X) :- allied_with(X,Y), traitor(Y).

% --- Kingmaker ---
kingmaker(X) :- allied_with(X,Y), allied_with(X,Z), powerful(Y), powerful(Z), house_of(Y,H1), house_of(Z,H2), H1 != H2, not powerful(X).
kingmaker(X) :- influences(X,Y), influences(X,Z), house_of(Y,H1), house_of(Z,H2), H1 != H2.

% --- Integrity constraints ---
:- allied_with(X,Y), enemy_of(X,Y).
:- controls(X,T1), controls(X,T2), T1 != T2.
:- vassal_of(X,Y), vassal_of(X,Z), Y != Z.
:- married_to(X,Y), married_to(X,Z), Y != Z.
:- heir_of(X,Y), heir_of(X,Z), Y != Z.
:- vassal_of(X,X).
