---------------------- MODULE PythonOutputValidation ----------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Files, RejectInvalid
VARIABLES validity, validated, conversions, rejected, phase, candidate
vars == <<validity, validated, conversions, rejected, phase, candidate>>

(* A file represents one database/source pair after the worker barrier.
   This models the validation decision, not Unicode decoding or SQLite IO. *)
Init ==
    /\ validity \in [Files -> {"valid", "invalid"}]
    /\ validated = {}
    /\ conversions = [f \in Files |-> 0]
    /\ rejected = FALSE
    /\ phase = "validating"
    /\ candidate = "pending"

Validate(f) ==
    /\ phase = "validating"
    /\ f \in Files \ validated
    /\ validated' = validated \cup {f}
    /\ conversions' = [conversions EXCEPT ![f] = @ + 1]
    /\ rejected' = (rejected \/ (RejectInvalid /\ validity[f] = "invalid"))
    /\ UNCHANGED <<validity, phase, candidate>>

Finalize ==
    /\ phase = "validating"
    /\ validated = Files
    /\ candidate' = IF rejected THEN "discarded" ELSE "published"
    /\ phase' = "finished"
    /\ UNCHANGED <<validity, validated, conversions, rejected>>

Finish == /\ phase = "finished" /\ UNCHANGED vars
Spec == Init /\ [][(\E f \in Files : Validate(f)) \/ Finalize \/ Finish]_vars

OncePerDatabaseAndSource == \A f \in Files :
    conversions[f] = (IF f \in validated THEN 1 ELSE 0)
NoPublicationAfterInvalidOutput ==
    (\E f \in Files : validity[f] = "invalid") => candidate # "published"
AllSourcesValidatedBeforePublication == candidate = "published" => validated = Files
RejectedOutputStaysRejected ==
    RejectInvalid /\ (\E f \in validated : validity[f] = "invalid") => rejected
=============================================================================
