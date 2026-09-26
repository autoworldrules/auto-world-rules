% =====================================================================
% RULE BASE: The Alchemist's Cauldron
% =====================================================================
% Elixirs are brewed from exactly two distinct inputs (raw reagents or
% other elixirs). An elixir can only be brewed if BOTH inputs are
% themselves obtainable, so every claim about an elixir silently depends
% on its whole recipe tree. Curses travel upward into products and
% sideways between reagents that share a cauldron.
%
% Story (base) relations:
%   r(C,A)  elixir C is brewed from input A      (at most two inputs)
%   s(X,X)  X is a raw reagent, gathered not brewed
%   t(X,X)  X is cursed (observed at a source; also derived below)
% Derived relations:
%   u(X,X)  X is obtainable
%   v(X,X)  X can actually be brewed
%   w(A,C)  A is an active input of C
%   p(A,C)  raw reagent A ends up inside C (provenance)
%   q(A,B)  A and B share a cauldron (co-inputs of a brewable elixir)
%   x(C,D)  C and D are kin elixirs (same generation)
%   y(A,B)  A spoils B (curse transfer)
% No negation as failure, no choice rules, no numbers.
% =====================================================================

% --- Obtainability: AND/OR recursion with a two-distinct-inputs threshold
u(X,X) :- s(X,X).
v(C,C) :- r(C,A), r(C,B), u(A,A), u(B,B), A != B.
u(C,C) :- v(C,C).

% --- Active inputs: an input only counts if its product is brewable
w(A,C) :- r(C,A), v(C,C).

% --- Provenance: a chain where every hop needs a brewability check
p(A,C) :- w(A,C), s(A,A).
p(A,D) :- p(A,C), w(C,D).

% --- Cauldron-mates: symmetric relation through a shared product
q(A,B) :- w(A,C), w(B,C), A != B.

% --- Kin elixirs: same-generation recursion (not transitive)
x(C,D) :- w(A,C), w(A,D), C != D.
x(C,D) :- w(A,C), w(B,D), x(A,B), C != D.

% --- Curses: spread upward into products and sideways to cauldron-mates
y(A,C) :- w(A,C), t(A,A).
y(A,B) :- q(A,B), t(A,A).
t(X,X) :- y(A,X).

% --- Integrity constraints
% an elixir has at most two inputs
:- r(C,A), r(C,B), r(C,D), A != B, A != D, B != D.
% raw reagents are gathered, never brewed
:- s(X,X), r(X,A).

% ---------------------------------------------------------------------
% Example hard story (8 entities, 14 facts) found by search.
% Query y(e6,e1): OPEC 13, OPEEC 23, BL 3.4
%   r(e0,e2). r(e0,e4). r(e1,e4). r(e1,e6). r(e2,e1). r(e2,e7).
%   r(e3,e1). r(e3,e4). r(e5,e0). r(e5,e1).
%   s(e4,e4). s(e6,e6). s(e7,e7). t(e0,e0).
% ---------------------------------------------------------------------
