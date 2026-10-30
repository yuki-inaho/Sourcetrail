------------------------- MODULE ExternalIndexing -------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS Commands, RetainFailure
VARIABLES planned, attempted, settled, succeeded, failed, outcomes, counts,
          failureSeen, phase, candidate, cleaned, notification

vars == <<planned, attempted, settled, succeeded, failed, outcomes, counts,
          failureSeen, phase, candidate, cleaned, notification>>
ProcessOutcomes == {"success", "transport-error", "nonzero-exit"}

(* A bounded batch contains two or three commands.  Begin records an attempt,
   including attempts that subsequently report a launch/transport error.
   Settle abstracts the adapter's completed process observation, not the OS. *)
Init ==
    /\ planned \in SUBSET Commands
    /\ Cardinality(planned) \in 2..3
    /\ attempted = {}
    /\ settled = {}
    /\ succeeded = {}
    /\ failed = {}
    /\ outcomes = [c \in planned |-> "pending"]
    /\ counts = [attempted |-> 0, settled |-> 0, succeeded |-> 0, failed |-> 0]
    /\ failureSeen = FALSE
    /\ phase = "running"
    /\ candidate = "pending"
    /\ cleaned = FALSE
    /\ notification = "none"

Begin(c) ==
    /\ phase = "running"
    /\ c \in planned \ attempted
    /\ attempted' = attempted \cup {c}
    /\ counts' = [counts EXCEPT !.attempted = @ + 1]
    /\ UNCHANGED <<planned, settled, succeeded, failed, outcomes,
                    failureSeen, phase, candidate, cleaned, notification>>

Settle(c, outcome) ==
    /\ phase = "running"
    /\ c \in attempted \ settled
    /\ outcome \in ProcessOutcomes
    /\ settled' = settled \cup {c}
    /\ outcomes' = [outcomes EXCEPT ![c] = outcome]
    /\ succeeded' = IF outcome = "success" THEN succeeded \cup {c} ELSE succeeded
    /\ failed' = IF outcome = "success" THEN failed ELSE failed \cup {c}
    /\ counts' = [counts EXCEPT
           !.settled = @ + 1,
           !.succeeded = @ + (IF outcome = "success" THEN 1 ELSE 0),
           !.failed = @ + (IF outcome = "success" THEN 0 ELSE 1)]
    /\ failureSeen' = IF RetainFailure
                      THEN failureSeen \/ outcome # "success"
                      ELSE outcome # "success"
    /\ UNCHANGED <<planned, attempted, phase, candidate, cleaned, notification>>

(* The task barrier is a precondition.  The counters alone do not implement
   thread joining, nor do they validate the candidate's database contents. *)
Finalize ==
    /\ phase = "running"
    /\ settled = planned
    /\ candidate' \in IF failureSeen THEN {"discarded"} ELSE {"published", "discarded"}
    /\ phase' = "finalized"
    /\ UNCHANGED <<planned, attempted, settled, succeeded, failed, outcomes,
                    counts, failureSeen, cleaned, notification>>

Cleanup ==
    /\ phase = "finalized"
    /\ cleaned' = TRUE
    /\ phase' = "cleaned"
    /\ UNCHANGED <<planned, attempted, settled, succeeded, failed, outcomes,
                    counts, failureSeen, candidate, notification>>

Notify ==
    /\ phase = "cleaned"
    /\ notification' = IF failureSeen THEN "failure" ELSE "success"
    /\ phase' = "notified"
    /\ UNCHANGED <<planned, attempted, settled, succeeded, failed, outcomes,
                    counts, failureSeen, candidate, cleaned>>

Finish == /\ phase = "notified" /\ UNCHANGED vars
Next == (\E c \in planned : Begin(c))
        \/ (\E c \in planned, outcome \in ProcessOutcomes : Settle(c, outcome))
        \/ Finalize \/ Cleanup \/ Notify \/ Finish
Spec == Init /\ [][Next]_vars

TypeInvariant ==
    /\ planned \subseteq Commands
    /\ Cardinality(planned) \in 2..3
    /\ attempted \subseteq planned
    /\ settled \subseteq planned
    /\ succeeded \subseteq planned
    /\ failed \subseteq planned
    /\ outcomes \in [planned -> (ProcessOutcomes \cup {"pending"})]
    /\ counts \in [{"attempted", "settled", "succeeded", "failed"} -> 0..3]
    /\ failureSeen \in BOOLEAN
    /\ phase \in {"running", "finalized", "cleaned", "notified"}
    /\ candidate \in {"pending", "published", "discarded"}
    /\ cleaned \in BOOLEAN
    /\ notification \in {"none", "success", "failure"}

OutcomeAccounting ==
    /\ settled \subseteq attempted
    /\ succeeded \cap failed = {}
    /\ succeeded \cup failed = settled
    /\ succeeded = {c \in planned : outcomes[c] = "success"}
    /\ failed = {c \in planned : outcomes[c] \in {"transport-error", "nonzero-exit"}}
    /\ counts.attempted = Cardinality(attempted)
    /\ counts.settled = Cardinality(settled)
    /\ counts.succeeded = Cardinality(succeeded)
    /\ counts.failed = Cardinality(failed)
    /\ counts.succeeded + counts.failed = counts.settled
    /\ counts.settled <= counts.attempted

FailureIsSticky == failureSeen = (failed # {})
SettledBeforeFinalization == phase # "running" => settled = planned
NoPublicationAfterFailure == failed # {} => candidate # "published"
FailedCandidateDiscarded == phase # "running" /\ failed # {} => candidate = "discarded"
TerminalOutcomeMatchesFailures == phase = "notified" =>
    /\ (notification = "success") = (failed = {})
    /\ (notification = "failure") = (failed # {})
CleanupBeforeNotification == notification # "none" =>
    /\ cleaned
    /\ phase = "notified"
    /\ candidate # "pending"

=============================================================================
