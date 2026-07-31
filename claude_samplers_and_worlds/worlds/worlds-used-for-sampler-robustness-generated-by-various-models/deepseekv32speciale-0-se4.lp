% Domain base facts  
person(p1). person(p2). person(p3). person(p4). person(p5). person(p6). person(p7).          

club(c1). club(c2). club(c3).
          
member(p1,c1). member(p2,c1). member(p3,c1).          
member(p4,c2). member(p5,c2).          
member(p6,c3). member(p7,c3).

knows(p1,p2). knows(p1,p3). knows(p2,p3). 
knows(p4,p5). knows(p6,p7). knows(p1,p4). 
knows(p2,p5). knows(p3,p6). knows(p4,p7). 
knows(p5,p1). knows(p6,p2). knows(p7,p3).          
   
% Rules        
   
% Symmetry of knows        
knows(Y,X) :- knows(X,Y).     
   
% For each known pair, they must be either friends or enemies (choice)           
{friend(X,Y), enemy(X,Y)} :- knows(X,Y).       
   
% Cannot be both friend and enemy
:- friend(X,Y), enemy(X,Y).
   
% Must be at least one (friend or enemy) for each known pair      
:- knows(X,Y), not friend(X,Y), not enemy(X,Y).      
      
% Symmetry of friendship and enmity
friend(Y,X) :- friend(X,Y).   
enemy(Y,X) :- enemy(X,Y).        
   
% Trust and distrust from relationships      
trust(X,Y) :- friend(X,Y). 
distrust(X,Y) :- enemy(X,Y).
   
% Transitivity of trust
trust(X,Z) :- trust(X,Y), trust(Y,Z).     
      
% Transitivity of distrust    
distrust(X,Z) :- distrust(X,Y), distrust(Y,Z).       
   
% Distrust propagation: if X distrusts Y and Y trusts Z, then X distrusts Z   
distrust(X,Z) :- distrust(X,Y), trust(Y,Z).        
      
% Trust and distrust cannot coexist    
:- trust(X,Y), distrust(X,Y).    
   
% Mutual friends and enemies  
mutualFriend(X,Y) :- friend(X,Z), friend(Y,Z), X != Y.     
mutualEnemy(X,Y) :- enemy(X,Z), enemy(Y,Z), X != Y.   
   
% Ally from mutual friend or mutual enemy
ally(X,Y) :- mutualFriend(X,Y).    
ally(X,Y) :- mutualEnemy(X,Y).          
           
% Rival definition: X is rival of Y if X is friend of Z and Y is enemy of Z      
rival(X,Y) :- friend(X,Z), enemy(Y,Z), X != Y.      
% Symmetry of rivalry        
rival(Y,X) :- rival(X,Y).          
         
% Ally and rival cannot both hold  
:- ally(X,Y), rival(X,Y).   
         
% Trust from ally, distrust from rival    
trust(X,Y) :- ally(X,Y).         
distrust(X,Y) :- rival(X,Y).
       
% Club roles: president and secretary choice from members
{president(P,C)} :- member(P,C). 
{secretary(P,C)} :- member(P,C).           
         
% Helper predicates for existence      
has_president(C) :- president(P,C).    
has_secretary(C) :- secretary(P,C).       
       
% Each club must have at least one president and one secretary 
:- club(C), not has_president(C).
:- club(C), not has_secretary(C).      
      
% At most one president and one secretary per club       
:- president(P1,C), president(P2,C), P1 != P2.        
:- secretary(P1,C), secretary(P2,C), P1 != P2.     
      
% President and secretary must be different persons
:- president(P,C), secretary(P,C).        
      
% President and secretary must be members (safety)    
:- president(P,C), not member(P,C).          
:- secretary(P,C), not member(P,C).       
      
% Members trust their president  
trust(M, P) :- president(P,C), member(M,C), M != P.   
      
% A member cannot be rival with the president or secretary           
:- president(P,C), member(M,C), rival(M,P).           
:- secretary(S,C), member(M,C), rival(M,S).           

% President and secretary trust each other
trust(P,S) :- president(P,C), secretary(S,C).         
trust(S,P) :- president(P,C), secretary(S,C).
      
% President and secretary cannot be enemies           
:- president(P,C), secretary(S,C), enemy(P,S).           
      
% Rival clubs arise from enemy relationships between members         
rivalClubs(C1,C2) :- member(P1,C1), member(P2,C2), enemy(P1,P2), C1 != C2.       

% Allied clubs arise from trust between presidents       
alliedClubs(C1,C2) :- president(P1,C1), president(P2,C2), trust(P1,P2).          

% A club cannot be both rival and allied with another    
:- rivalClubs(C1,C2), alliedClubs(C1,C2).    

% Presidents of rival clubs become rivals    
rival(P1,P2) :- rivalClubs(C1,C2), president(P1,C1), president(P2,C2).   
