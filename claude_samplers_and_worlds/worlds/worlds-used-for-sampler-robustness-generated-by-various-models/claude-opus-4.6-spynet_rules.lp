% ═══════════════════════════════════════════════════════════════════════════
% SPYNET: Intelligence & Security Network Rules
% ═══════════════════════════════════════════════════════════════════════════
%
% Domain: Intelligence agencies, operatives, classified information, trust.
%
% Constraint: at most ONE negation-as-failure (not) per rule.
% Multi-condition negation is factored into auxiliary predicates.
%
% Reasoning challenges (different from NoRa):
%   - 50+ NAF rules (NoRa: 0) — defaults with exceptions
%   - Multi-hop authorization chains with conditional revocation
%   - Trust propagation with distrust override
%   - Cascading compromise detection
%   - Target proof depth 8-12
%
% Entity types: agents (persons), assets (resources/intel/locations)
% ═══════════════════════════════════════════════════════════════════════════

% ─── LAYER 1: ORGANIZATIONAL STRUCTURE ────────────────────────────────────

allied_with(Y,X) :- allied_with(X,Y), X != Y.
hostile_to(Y,X) :- hostile_to(X,Y), X != Y.

commands(X,Y) :- reports_to(Y,X).
commands(X,Y) :- commands(X,Z), reports_to(Y,Z), X != Y.

subordinate_of(X,Y) :- commands(Y,X).
subordinate_of(Y,X) :- commands(X,Y).

same_cell(X,Y) :- reports_to(X,H), reports_to(Y,H), X != Y.
same_cell(Y,X) :- same_cell(X,Y), X != Y.

same_network(X,Y) :- same_cell(X,Y).
same_network(X,Y) :- same_cell(X,Z), same_network(Z,Y), X != Y.
same_network(Y,X) :- same_network(X,Y), X != Y.

is_handler(X,X) :- reports_to(Y,X).
is_field_agent(X,X) :- reports_to(X,Y), not is_handler(X,X).
is_senior(X,X) :- is_handler(X,X), reports_to(X,Y).
has_superior(X,X) :- reports_to(X,Y).
is_chief(X,X) :- is_handler(X,X), not has_superior(X,X).

% ─── LAYER 2: TRUST NETWORK ──────────────────────────────────────────────

trusts_peer(Y,X) :- trusts_peer(X,Y), X != Y.

trusts(X,Y) :- trusts_peer(X,Y), not distrusts(X,Y).
trusts(X,Y) :- commands(X,Y), not distrusts(X,Y).
trusts(X,Y) :- trusts(X,Z), trusts_peer(Z,Y), same_network(X,Y), X != Y, not distrusts(X,Y).
trusts(X,Y) :- vouches_for(Z,Y), trusts(X,Z), X != Y, not distrusts(X,Y).

distrusts(X,Y) :- suspects(X,Y).
distrusts(X,Y) :- known_hostile(Y,Y), same_network(X,Y).
distrusts(X,Y) :- compromised(Y,Y), aware_of_compromise(X,Y).

aware_of_compromise(X,Y) :- commands(X,Y), compromised(Y,Y).
aware_of_compromise(X,Y) :- commands(X,Z), aware_of_compromise(Z,Y), X != Y.

% Vouching: aux predicate bundles the two negative conditions
vouch_blocked(X,Y) :- suspects(X,Y).
vouch_blocked(X,Y) :- compromised(X,X), commands(X,Y).
vouches_for(X,Y) :- commands(X,Y), trusts(X,Y), not vouch_blocked(X,Y).

% ─── LAYER 3: INTELLIGENCE & CLEARANCE ───────────────────────────────────

outranks(senior,junior).
outranks(top,senior).
outranks(top,junior).

cleared_for(A,R) :- has_clearance(A,L), classified_as(R,L).
cleared_for(A,R) :- has_clearance(A,L1), classified_as(R,L2), outranks(L1,L2).

authorized(A,R) :- assigned_to(A,R).
authorized(A,R) :- commands(C,A), authorized(C,R), trusts(C,A).
authorized(A,R) :- vouches_for(V,A), authorized(V,R), not access_denied(A,R).
authorized(A,R) :- delegated_to(A,R).

% Delegation: aux bundles access_denied + compromised
can_delegate(B,A) :- trusts(B,A), same_network(B,A), not compromised(B,B).
delegated_to(A,R) :- authorized(B,R), can_delegate(B,A), not access_denied(A,R).

% Full access
can_access(A,R) :- holds(A,R).
can_access(A,R) :- cleared_for(A,R), authorized(A,R), not access_denied(A,R).

% Access denied
access_denied(A,R) :- compromised(A,A), classified_as(R,senior).
access_denied(A,R) :- compromised(A,A), classified_as(R,top).
access_denied(A,R) :- under_investigation(A,A), classified_as(R,top).
access_denied(A,R) :- info_barrier(A,R).

% Information barrier
info_barrier(A,R) :- holds(B,R), known_hostile(A,A), same_network(A,B).
info_barrier(A,R) :- can_access(B,R), contact_with(A,B), known_hostile(A,A).

contact_with(Y,X) :- contact_with(X,Y), X != Y.
contact_with(X,Y) :- met_with(X,Y).
contact_with(X,Y) :- same_cell(X,Y).

% ─── LAYER 4: COVER & COMPROMISE ─────────────────────────────────────────

has_cover(X,X) :- cover_as(X,Y).
blown_cover(X,X) :- cover_as(X,C), identified_by(Z,X), Z != X.

identified_by(Z,X) :- known_hostile(Z,Z), has_intel_on(Z,X), contact_with(Z,X).
identified_by(Z,X) :- known_hostile(Z,Z), has_intel_on(Z,X), same_network(Z,X).

has_intel_on(Z,X) :- holds(Z,R), concerns(R,X).
has_intel_on(Z,X) :- can_access(Z,R), concerns(R,X).

compromised(X,X) :- blown_cover(X,X).
compromised(X,X) :- captured(X,X).
compromised(X,X) :- turned(X,X).

turned(X,X) :- recruited_by(X,Y), known_hostile(Y,Y).

known_hostile(X,X) :- flagged_hostile(X,X).
known_hostile(X,X) :- turned(X,X), aware_of_compromise(Y,X).

double_agent(X,X) :- same_network(X,Y), known_hostile(Y,Y), not known_hostile(X,X), turned(X,X).

% ─── LAYER 5: COUNTER-INTELLIGENCE ───────────────────────────────────────

suspects(X,Y) :- commands(X,Y), anomalous(Y,Y).
suspects(X,Y) :- commands(X,Y), unexplained_contact(Y,Y).
suspects(X,Y) :- trusts_peer(X,Z), suspects(Z,Y), X != Y, not trusts(X,Y).

anomalous(X,X) :- met_with(X,Y), known_hostile(Y,Y), not approved_meeting(X,Y).
anomalous(X,X) :- leaked_intel(R,R), last_handler(R,X).

unexplained_contact(X,X) :- contact_with(X,Y), known_hostile(Y,Y), not approved_meeting(X,Y).

approved_meeting(X,Y) :- same_cell(X,Y).
approved_meeting(X,Y) :- commands(X,Y).
approved_meeting(X,Y) :- commands(Y,X).
approved_meeting(X,Y) :- same_network(X,Y), trusts(X,Y).
approved_meeting(Y,X) :- approved_meeting(X,Y), X != Y.

under_investigation(X,X) :- suspects(Y,X), commands(Y,X).
under_investigation(X,X) :- counter_intel_target(X,X).

counter_intel_target(X,X) :- double_agent(X,X).
counter_intel_target(X,X) :- compromised(X,X), not confirmed_loyal(X,X).
counter_intel_target(X,X) :- anomalous(X,X), unexplained_contact(X,X).

% Confirmed loyal: aux bundles compromised checks on vouchers
valid_vouch(A,X) :- vouches_for(A,X), not compromised(A,A).
confirmed_loyal(X,X) :- valid_vouch(A,X), valid_vouch(B,X), A != B.

% ─── LAYER 6: CASCADING CONSEQUENCES ─────────────────────────────────────

leaked_intel(R,R) :- can_access(A,R), compromised(A,A).
leaked_intel(R,R) :- can_access(A,R), double_agent(A,A).
leaked_intel(R,R) :- holds(A,R), under_investigation(A,A), not intel_secured(R,R).

% Intel secured: aux bundles two negative conditions
intel_dirty(R,R) :- tainted(R,R).
intel_dirty(R,R) :- leaked_intel(R,R).
intel_secured(R,R) :- classified_as(R,L), not intel_dirty(R,R).

cell_exposed(X,X) :- reports_to(X,H), compromised(H,H).
cell_exposed(X,X) :- same_cell(X,Y), cell_exposed(Y,Y), compromised(Y,Y).

at_risk(X,X) :- cell_exposed(X,X), not confirmed_loyal(X,X).
at_risk(X,X) :- same_cell(X,Y), compromised(Y,Y), not confirmed_loyal(X,X).
at_risk(X,X) :- trusts(X,Y), compromised(Y,Y), not aware_of_compromise(X,Y).

% ─── LAYER 7: OPERATIONAL SECURITY ───────────────────────────────────────

% Safe channel: aux bundles four negative conditions
channel_blocked(X,Y) :- compromised(X,X), trusts(X,Y).
channel_blocked(X,Y) :- compromised(Y,Y), trusts(X,Y).
channel_blocked(X,Y) :- at_risk(X,X), trusts(X,Y).
channel_blocked(X,Y) :- at_risk(Y,Y), trusts(X,Y).
safe_channel(X,Y) :- trusts(X,Y), trusts(Y,X), not channel_blocked(X,Y).
safe_channel(Y,X) :- safe_channel(X,Y), X != Y.

can_reach(X,Y) :- safe_channel(X,Y).
can_reach(X,Y) :- safe_channel(X,Z), can_reach(Z,Y), X != Y.
can_reach(Y,X) :- can_reach(X,Y), X != Y.

isolated(X,X) :- reports_to(X,Y), not can_reach(X,Y).
isolated(X,X) :- is_field_agent(X,X), not can_reach(X,Y), commands(Y,X).

partition(X,Y) :- same_network(X,Y), not can_reach(X,Y), X != Y.

% ─── LAYER 8: STRATEGIC ASSESSMENT ───────────────────────────────────────

% Reliable: aux bundles multiple blocking conditions
unreliable(X,X) :- compromised(X,X).
unreliable(X,X) :- under_investigation(X,X).
unreliable(X,X) :- at_risk(X,X).
unreliable(X,X) :- anomalous(X,X).
reliable(X,X) :- confirmed_loyal(X,X), not unreliable(X,X).
reliable(X,X) :- vouches_for(V,X), reliable(V,V), not unreliable(X,X).

% Operational: aux bundles isolated + captured
nonoperational(X,X) :- isolated(X,X).
nonoperational(X,X) :- captured(X,X).
operational(X,X) :- reliable(X,X), not nonoperational(X,X).

high_value(X,X) :- reliable(X,X), has_clearance(X,top), holds(X,R), classified_as(R,top).
high_value(X,X) :- reliable(X,X), is_chief(X,X), not at_risk(X,X).

strategic_asset(X,X) :- reliable(X,X), has_clearance(X,top), not at_risk(X,X).
strategic_asset(X,X) :- reliable(X,X), is_chief(X,X), not at_risk(X,X).

target(X,X) :- high_value(X,X), known_hostile(X,X).
target(X,X) :- high_value(X,X), has_intel_on(Y,X), same_network(Y,X), not same_network(X,Y).

% Needs extraction: aux bundles operational + captured
extraction_blocked(X,X) :- operational(X,X).
extraction_blocked(X,X) :- captured(X,X).
needs_extraction(X,X) :- at_risk(X,X), not extraction_blocked(X,X).
needs_extraction(X,X) :- compromised(X,X), isolated(X,X), not captured(X,X).

extractable(X,X) :- needs_extraction(X,X), can_reach(X,Y), commands(Y,X), reliable(Y,Y).
extractable(X,X) :- needs_extraction(X,X), same_cell(X,Y), operational(Y,Y), can_reach(Y,Z), commands(Z,X).

% ─── LAYER 9: NETWORK VULNERABILITY ──────────────────────────────────────

bottleneck(X,X) :- safe_channel(X,A), safe_channel(X,B), A != B, not safe_channel(A,B).

critical_node(X,X) :- is_handler(X,X), not redundant_handler(X,X).
redundant_handler(X,X) :- reports_to(A,X), reports_to(A,Y), X != Y, is_handler(Y,Y).

vulnerable_chain(X,Y) :- commands(X,Y), at_risk(X,X).
vulnerable_chain(X,Y) :- commands(X,Z), at_risk(Z,Z), vulnerable_chain(Z,Y).

% Network status: aux bundles multiple blocking conditions
network_impaired(X,X) :- compromised(X,X).
network_impaired(X,X) :- isolated(X,X).
network_impaired(X,X) :- at_risk(X,X).
network_intact(X,X) :- is_chief(X,X), not network_impaired(X,X).
network_degraded(X,X) :- is_chief(X,X), at_risk(X,X), not compromised(X,X).
network_failed(X,X) :- is_chief(X,X), compromised(X,X).
network_failed(X,X) :- is_chief(X,X), isolated(X,X).

% ─── LAYER 10: INFORMATION PROVENANCE ─────────────────────────────────────

source_of(X,R) :- holds(X,R), not was_delegated(X,R).
was_delegated(X,R) :- delegated_to(X,R).

tainted(R,R) :- source_of(X,R), compromised(X,X).
tainted(R,R) :- source_of(X,R), turned(X,X).
tainted(R,R) :- leaked_intel(R,R), classified_as(R,top).

verified_clean(R,R) :- classified_as(R,L), not intel_dirty(R,R).

actionable(A,R) :- can_access(A,R), verified_clean(R,R), not under_investigation(A,A).

% ─── LAYER 11: OPERATION READINESS ────────────────────────────────────────

op_viable(A,R) :- actionable(A,R), operational(A,A), not isolated(A,A).

recommend_action(X,R) :- op_viable(X,R), reliable(X,X), has_clearance(X,top), not tainted(R,R).
recommend_action(X,R) :- op_viable(X,R), vouches_for(V,X), recommend_action(V,R2), same_network(X,V).

% ─── LAYER 12: ALLIANCE REASONING ────────────────────────────────────────

indirect_ally(X,Y) :- allied_with(X,Z), allied_with(Z,Y), X != Y, not hostile_to(X,Y).
indirect_ally(Y,X) :- indirect_ally(X,Y), X != Y.

% Potential ally: aux bundles hostile + allied checks
already_related(X,Y) :- hostile_to(X,Y).
already_related(X,Y) :- allied_with(X,Y).
potential_ally(X,Y) :- hostile_to(X,Z), hostile_to(Y,Z), X != Y, not already_related(X,Y).

shares_threat(X,Y) :- hostile_to(X,Z), hostile_to(Y,Z), allied_with(X,Y), X != Y.
shares_threat(Y,X) :- shares_threat(X,Y), X != Y.

unstable_alliance(X,Y) :- allied_with(X,Y), infiltrated(X,X).
unstable_alliance(X,Y) :- allied_with(X,Y), infiltrated(Y,Y).
unstable_alliance(Y,X) :- unstable_alliance(X,Y), X != Y.

infiltrated(X,X) :- same_network(X,Y), turned(Y,Y), not aware_of_compromise(X,Y).

% ─── LAYER 13: DEEP CONDITIONAL SECURITY ──────────────────────────────────

fully_secure(X,X) :- reliable(X,X), operational(X,X), can_reach(X,C), is_chief(C,C), not vulnerable_chain(C,X).

asset_protected(R,R) :- holds(X,R), fully_secure(X,X).
asset_protected(R,R) :- assigned_to(X,R), fully_secure(X,X), verified_clean(R,R).

containment_needed(X,X) :- compromised(X,X), holds(X,R), classified_as(R,top), not captured(X,X).
containment_needed(X,X) :- cell_exposed(X,X), holds(X,R), classified_as(R,senior), not confirmed_loyal(X,X).

containment_possible(X,X) :- containment_needed(X,X), commands(Y,X), operational(Y,Y), can_reach(Y,X).

damage_critical(X,X) :- containment_needed(X,X), not containment_possible(X,X).
damage_critical(X,X) :- network_failed(C,C), same_network(X,C), holds(X,R), classified_as(R,top).

% ═══════════════════════════════════════════════════════════════════════════
% TYPE MARKERS
% ═══════════════════════════════════════════════════════════════════════════

is_agent(X) :- reports_to(X,Y).
is_agent(X) :- reports_to(Y,X).
is_agent(X) :- trusts_peer(X,Y).
is_agent(X) :- has_clearance(X,L).
is_agent(X) :- holds(X,R).
is_agent(X) :- cover_as(X,C).
is_agent(X) :- met_with(X,Y).
is_agent(X) :- recruited_by(X,Y).
is_agent(X) :- flagged_hostile(X,X).
is_agent(X) :- captured(X,X).
is_agent(X) :- assigned_to(X,R).
is_agent(X) :- stationed_at(X,R).

is_asset(R) :- classified_as(R,L).
is_asset(R) :- concerns(R,X).
is_asset(R) :- holds(X,R).
is_asset(R) :- assigned_to(X,R).

is_level(L) :- has_clearance(X,L).
is_level(L) :- classified_as(R,L).

% ═══════════════════════════════════════════════════════════════════════════
% INTEGRITY CONSTRAINTS
% ═══════════════════════════════════════════════════════════════════════════

% Type disjointness
:- is_agent(X), is_asset(X).
:- is_agent(X), is_level(X).
:- is_asset(X), is_level(X).

% Self-reference
:- reports_to(X,X).
:- trusts_peer(X,X).
:- met_with(X,X).
:- allied_with(X,X).
:- hostile_to(X,X).
:- contact_with(X,X).
:- cover_as(X,X).
:- recruited_by(X,X).

% Mutual exclusion
:- allied_with(X,Y), hostile_to(X,Y).
:- commands(X,Y), commands(Y,X).

% Uniqueness
:- has_clearance(X,L1), has_clearance(X,L2), L1 != L2.
:- classified_as(R,L1), classified_as(R,L2), L1 != L2.
:- reports_to(X,Y), reports_to(X,Z), Y != Z.
:- cover_as(X,Y), cover_as(X,Z), Y != Z.
:- recruited_by(X,Y), recruited_by(X,Z), Y != Z.

% Access
:- holds(X,R), classified_as(R,top), has_clearance(X,junior).
:- holds(X,R), classified_as(R,senior), has_clearance(X,junior).

% Logical consistency
:- compromised(X,X), confirmed_loyal(X,X).
:- reliable(X,X), under_investigation(X,X).
:- operational(X,X), captured(X,X).
:- target(X,X), confirmed_loyal(X,X).
:- known_hostile(X,X), confirmed_loyal(X,X).

% Structural exclusivity
:- safe_channel(X,Y), compromised(X,X).
:- safe_channel(X,Y), compromised(Y,Y).
:- vouches_for(X,Y), compromised(X,X).
:- vouches_for(X,Y), distrusts(X,Y).
:- actionable(X,R), compromised(X,X).
:- recommend_action(X,R), compromised(X,X).
:- recommend_action(X,R), tainted(R,R).
:- delegated_to(Y,R), access_denied(Y,R).
:- extractable(X,X), captured(X,X).

% Status exclusivity
:- fully_secure(X,X), at_risk(X,X).
:- fully_secure(X,X), isolated(X,X).
:- fully_secure(X,X), compromised(X,X).
:- network_intact(X,X), network_failed(X,X).
:- network_intact(X,X), network_degraded(X,X).
:- intel_secured(R,R), leaked_intel(R,R).
:- verified_clean(R,R), tainted(R,R).
:- asset_protected(R,R), leaked_intel(R,R).
:- reliable(X,X), compromised(X,X).
:- reliable(X,X), known_hostile(X,X).

% Cardinality
:- reports_to(A,X), reports_to(B,X), reports_to(C,X), reports_to(D,X), A != B, A != C, A != D, B != C, B != D, C != D.
:- holds(X,A), holds(X,B), holds(X,C), A != B, A != C, B != C.

% Relationship exclusivity
:- commands(X,Y), trusts_peer(X,Y).
:- same_cell(X,Y), commands(X,Y).
:- same_cell(X,Y), known_hostile(X,X), not known_hostile(Y,Y).

% Cross-layer
:- high_value(X,X), compromised(X,X).
:- strategic_asset(X,X), under_investigation(X,X).
:- op_viable(X,R), access_denied(X,R).
:- double_agent(X,X), confirmed_loyal(X,X).
:- indirect_ally(X,Y), hostile_to(X,Y).
:- shares_threat(X,Y), hostile_to(X,Y).

% Network integrity
:- reliable(X,X), is_chief(C,C), same_network(X,C), network_failed(C,C).
