% DOMAIN BASE FACTS
person(aldric).
person(beatrix).
person(cedric).
person(darius).
person(elara).

faction(crimson_blade).
faction(silver_shield).

territory(northern_keep).
territory(southern_valley).

parent(aldric, cedric).
parent(beatrix, cedric).
married(aldric, beatrix).
leader(aldric, crimson_blade).
leader(darius, silver_shield).
controls(crimson_blade, northern_keep).
controls(silver_shield, southern_valley).
at_war(crimson_blade, silver_shield).
vassal(elara, darius).


% RULES
% 1. Sibling relations are derived from shared parents.
sibling(X,Y) :- parent(Z,X), parent(Z,Y), X != Y.

% 2. Marriage is a bidirectional relation.
married(X,Y) :- married(Y,X).

% 3. Constraint: Siblings cannot be married.
:- married(X,Y), sibling(X,Y).

% 4. A leader of a faction is inherently a member of that faction.
member(X,F) :- leader(X,F).

% 5. A vassal must make a choice: they are either loyal to their liege or they are a traitor.
{loyal(X,Y), traitor(X)} :- vassal(X,Y).

% 6. The liege relation is the inverse of the vassal relation.
liege(Y,X) :- vassal(X,Y).

% 7. The vassal relation can also be inferred from the liege relation.
vassal(X,Y) :- liege(Y,X).

% 8. Rivals are naturally enemies.
enemy(X,Y) :- rival(X,Y).

% 9. Rivalry is a bidirectional relationship.
rival(X,Y) :- rival(Y,X).

% 10. Enemy relationships are bidirectional.
enemy(X,Y) :- enemy(Y,X).

% 11. Alliances are bidirectional.
ally(X,Y) :- ally(Y,X).

% 12. Constraint: Two individuals cannot be both allies and enemies.
:- ally(X,Y), enemy(X,Y).

% 13. War between factions is bidirectional.
at_war(F1,F2) :- at_war(F2,F1).

% 14. Members of factions that are at war are considered enemies.
enemy(X,Y) :- member(X,F1), member(Y,F2), at_war(F1,F2).

% 15. A spy for a faction naturally targets the leader of that faction.
targets(X,Y) :- spy(X,F), leader(Y,F).

% 16. A traitor who is a member of a faction at war becomes a spy for the opposing faction.
spy(X,F1) :- member(X,F2), at_war(F1,F2), traitor(X).

% 17. An individual who targets someone they are sworn to be loyal to is marked as a traitor.
traitor(X) :- loyal(X,Y), targets(X,Y).

% 18. Loyalty implies a protective relationship.
protects(X,Y) :- loyal(X,Y).

% 19. Constraint: You cannot both protect and target the same individual.
:- targets(X,Y), protects(X,Y).

% 20. Allies generally support each other.
supports(X,Y) :- ally(X,Y).

% 21. A loyal vassal supports their liege.
supports(X,Y) :- vassal(X,Y), loyal(X,Y).

% 22. Constraint: You cannot support an individual you are targeting.
:- supports(X,Y), targets(X,Y).

% 23. Leaders of different factions have a choice: they can either be allies or enemies.
{ally(X,Y), enemy(X,Y)} :- leader(X,F1), leader(Y,F2), F1 != F2.

% 24. A faction leader resides in a territory controlled by their faction.
resides(X,T) :- controls(F,T), leader(X,F).

% 25. A vassal resides in the same territory as their liege.
resides(X,T) :- vassal(X,Y), resides(Y,T).

% 26. Constraint: An individual cannot reside in two different territories simultaneously.
:- resides(X,T1), resides(X,T2), T1 != T2.

% 27. A loyal child is considered the heir to their parent.
heir(X,Y) :- parent(Y,X), loyal(X,Y).

% 28. Constraint: A traitor cannot be an heir.
:- heir(X,Y), traitor(X).

% 29. An heir becomes the leader of a faction if the current leader is exiled.
leader(X,F) :- heir(X,Y), leader(Y,F), exiled(Y).

% 30. A traitor within a faction is exiled by the faction's leader.
exiled(X) :- traitor(X), member(X,F), leader(Y,F), X != Y.

% 31. Constraint: An exiled individual cannot reside in a territory controlled by their former faction.
:- exiled(X), resides(X,T), controls(F,T), member(X,F).

% 32. A vassal adopts the faction membership of their liege.
member(X,F) :- vassal(X,Y), member(Y,F).

% 33. A loyal spouse adopts the faction membership of their partner.
member(X,F) :- married(X,Y), member(Y,F), loyal(X,Y).

% 34. Two different heirs to the same individual are considered rivals.
rival(X,Y) :- heir(X,Z), heir(Y,Z), X != Y.

% 35. A member of a faction who resides in a territory controlled by a different faction is acting as a spy.
spy(X,F) :- resides(X,T), controls(F,T), member(X,F2), F != F2.

% 36. Constraint: A leader of a faction cannot be a spy within their own faction.
:- spy(X,F), leader(X,F).

% 37. A traitorous rival will target their rival.
targets(X,Y) :- rival(X,Y), traitor(X).

% 38. A loyal spouse will protect their partner.
protects(X,Y) :- married(X,Y), loyal(X,Y).

% 39. A faction gains control of an enemy territory if the enemy leader becomes a vassal to the attacking leader.
controls(F1,T) :- at_war(F1,F2), controls(F2,T), leader(X,F1), leader(Y,F2), vassal(Y,X).

% 40. A spy has the choice to either protect or target members of the faction they have infiltrated.
{protects(X,Y), targets(X,Y)} :- spy(X,F), member(Y,F).

% 41. Any individual who is a child is categorized as a person.
person(X) :- parent(Y,X).

% 42. Any individual who is a parent is categorized as a person.
person(X) :- parent(X,Y).

% 43. Any entity that has members is categorized as a faction.
faction(F) :- member(X,F).

% 44. Any entity that is controlled is categorized as a territory.
territory(T) :- controls(F,T).

% 45. Any married individual is categorized as a person.
person(X) :- married(X,Y).

% 46. Constraint: A faction cannot be at war with itself.
:- faction(F), at_war(F,F).

% 47. Constraint: A territory cannot be controlled by two different factions simultaneously.
:- territory(T), controls(F1,T), controls(F2,T), F1 != F2.

% 48. Any individual who leads a faction is categorized as a person.
person(X) :- leader(X,F).

% 49. Any entity that controls a territory is categorized as a faction.
faction(F) :- controls(F,T).

% 50. Any location where an individual resides is categorized as a territory.
territory(T) :- resides(X,T).
